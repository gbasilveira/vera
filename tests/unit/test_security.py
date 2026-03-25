"""Tests for SecurityManager (Casbin wrapper) — permission-centric model."""
import pytest
from core.security import SecurityManager


@pytest.fixture
def security():
    return SecurityManager(
        model_path="data/casbin/rbac_model.conf",
        policy_path="data/casbin/policy.csv",
    )


class TestEnforce:
    def test_owner_can_do_anything(self, security):
        assert security.enforce("owner", "gmail.check_inbox", "execute") is True
        assert security.enforce("owner", "llm.generate_structured", "execute") is True

    def test_owner_wildcard_action(self, security):
        """perm:sys:all grants * on *, so owner can use any action."""
        assert security.enforce("owner", "memory.auto_store", "enable") is True
        assert security.enforce("owner", "policy.rules", "manage") is True

    def test_guest_cannot_execute(self, security):
        assert security.enforce("guest", "gmail.check_inbox", "execute") is False

    def test_manager_can_use_business_tools(self, security):
        assert security.enforce("manager", "gmail.check_inbox", "execute") is True
        assert security.enforce("manager", "llm.stream", "execute") is True

    def test_manager_can_use_memory(self, security):
        assert security.enforce("manager", "memory.retrieve_context", "execute") is True

    def test_intern_cannot_use_gmail(self, security):
        assert security.enforce("intern", "gmail.check_inbox", "execute") is False

    def test_intern_can_use_memory_tools(self, security):
        assert security.enforce("intern", "memory.retrieve_context", "execute") is True

    def test_agent_editor_can_run_and_edit(self, security):
        assert security.enforce("agent_editor", "agent.run", "execute") is True
        assert security.enforce("agent_editor", "agent.config", "write") is True
        assert security.enforce("agent_editor", "agent.anything", "execute") is True

    def test_agent_editor_cannot_use_gmail(self, security):
        assert security.enforce("agent_editor", "gmail.send", "execute") is False

    def test_wildcard_match(self, security):
        """owner policy uses perm:sys:all — should match any tool."""
        assert security.enforce("owner", "any_plugin.any_tool", "execute") is True

    def test_deny_policy_overrides_allow(self, security):
        """manager has explicit deny on restricted_tool.run."""
        assert security.enforce("manager", "restricted_tool.run", "execute") is False


class TestPolicyManagement:
    def test_add_and_enforce_new_policy(self, security):
        security.add_policy("test_role", "test_tool.run", "execute", "allow")
        assert security.enforce("test_role", "test_tool.run", "execute") is True
        security.remove_policy("test_role", "test_tool.run", "execute")

    def test_remove_policy(self, security):
        security.add_policy("temp_role", "temp_tool.run", "execute", "allow")
        assert security.enforce("temp_role", "temp_tool.run", "execute") is True
        security.remove_policy("temp_role", "temp_tool.run", "execute")
        assert security.enforce("temp_role", "temp_tool.run", "execute") is False


class TestPermissionManagement:
    def test_register_permission(self, security):
        security.register_permission("perm:test:run", "test_ns.*", "execute")
        perms = security.get_all_permissions()
        names = [p["name"] for p in perms]
        assert "perm:test:run" in names
        # cleanup
        security.remove_policy("perm:test:run", "test_ns.*", "execute")

    def test_register_permission_without_prefix(self, security):
        """register_permission auto-adds perm: prefix if missing."""
        security.register_permission("test:auto_prefix", "auto.*", "execute")
        perms = security.get_all_permissions()
        names = [p["name"] for p in perms]
        assert "perm:test:auto_prefix" in names
        security.remove_policy("perm:test:auto_prefix", "auto.*", "execute")

    def test_register_permission_idempotent(self, security):
        security.register_permission("perm:test:idem", "idem.*", "execute")
        security.register_permission("perm:test:idem", "idem.*", "execute")  # second call
        count = sum(1 for p in security.get_all_permissions() if p["name"] == "perm:test:idem")
        assert count == 1
        security.remove_policy("perm:test:idem", "idem.*", "execute")

    def test_grant_permission_to_role(self, security):
        security.register_permission("perm:test:grant", "grantme.*", "execute")
        security.grant_permission_to_role("analyst", "perm:test:grant")
        assert security.enforce("analyst", "grantme.tool", "execute") is True
        # cleanup
        security.revoke_permission_from_role("analyst", "perm:test:grant")
        security.remove_policy("perm:test:grant", "grantme.*", "execute")

    def test_revoke_permission_from_role(self, security):
        security.register_permission("perm:test:revoke", "revokeme.*", "execute")
        security.grant_permission_to_role("temp_analyst", "perm:test:revoke")
        assert security.enforce("temp_analyst", "revokeme.tool", "execute") is True
        security.revoke_permission_from_role("temp_analyst", "perm:test:revoke")
        assert security.enforce("temp_analyst", "revokeme.tool", "execute") is False
        security.remove_policy("perm:test:revoke", "revokeme.*", "execute")

    def test_get_permissions_for_role(self, security):
        perms = security.get_permissions_for_role("manager")
        assert "perm:llm:generate" in perms
        assert "perm:gmail:all" in perms
        # role names should not appear here
        assert "intern" not in perms

    def test_get_all_permissions(self, security):
        perms = security.get_all_permissions()
        assert len(perms) > 0
        names = [p["name"] for p in perms]
        assert "perm:sys:all" in names
        assert "perm:llm:generate" in names

    def test_enforce_any(self, security):
        """enforce_any passes if ANY role in the list allows the action."""
        assert security.enforce_any(["intern", "manager"], "gmail.check_inbox", "execute") is True
        assert security.enforce_any(["intern", "guest"], "gmail.check_inbox", "execute") is False


class TestRoleManagement:
    def test_assign_role_to_user(self, security):
        security.assign_role("user123@test.com", "manager")
        roles = security.get_roles_for_user("user123@test.com")
        assert "manager" in roles
        security.revoke_role("user123@test.com", "manager")

    def test_revoke_role(self, security):
        security.assign_role("user456@test.com", "intern")
        security.revoke_role("user456@test.com", "intern")
        roles = security.get_roles_for_user("user456@test.com")
        assert "intern" not in roles

    def test_user_with_multiple_roles(self, security):
        """A user assigned multiple roles can exercise permissions from all of them."""
        security.assign_role("multi@test.com", "manager")
        security.assign_role("multi@test.com", "agent_editor")
        roles = security.get_roles_for_user("multi@test.com")
        assert "manager" in roles
        assert "agent_editor" in roles
        # Can use gmail (from manager) and edit agents (from agent_editor)
        assert security.enforce("multi@test.com", "gmail.send", "execute") is True
        assert security.enforce("multi@test.com", "agent.config", "write") is True
        # cleanup
        security.revoke_role("multi@test.com", "manager")
        security.revoke_role("multi@test.com", "agent_editor")

    def test_role_inheritance_via_assignment(self, security):
        """A user assigned 'manager' inherits manager's permissions."""
        security.assign_role("mgr_user@test.com", "manager")
        assert security.enforce("mgr_user@test.com", "memory.retrieve_context", "execute") is True
        security.revoke_role("mgr_user@test.com", "manager")

    def test_get_roles_excludes_perm_entries(self, security):
        """get_roles_for_user should only return role names, not perm:* entries."""
        security.assign_role("role_test@test.com", "intern")
        roles = security.get_roles_for_user("role_test@test.com")
        assert "intern" in roles
        assert not any(r.startswith("perm:") for r in roles)
        security.revoke_role("role_test@test.com", "intern")
