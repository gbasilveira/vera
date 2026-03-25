async def setup_kernel(plugins_dir: str = None) -> tuple:
    """
    Full kernel setup for production use.
    Returns (kernel, bus, vfs, secrets, security, tracer, deps_factory).

    Call this once at application startup (main.py in Phase 5).
    """
    import os
    from core.bus import create_bus
    from core.vfs import create_vfs
    from core.secrets import SecretsManager
    from core.security import SecurityManager
    from core.observability import setup_observability, wire_metrics_to_bus
    from core.deps import VeraDepsFactory
    from core.kernel import VeraKernel
    from core.auth.manager import AuthManager
    from core.auth.local import LocalAuthProvider

    bus = create_bus()
    vfs = create_vfs()
    secrets = SecretsManager()
    security = SecurityManager(bus=bus)
    tracer = setup_observability()
    wire_metrics_to_bus(bus)

    # Auth: built-in local provider; plugins may add more via register_auth_providers()
    # SecurityManager is passed so AuthManager can enrich user_roles from Casbin
    # and auto-migrate legacy DB roles on first login.
    auth_manager = AuthManager(vfs, security=security)
    auth_manager.register_provider(LocalAuthProvider())
    await auth_manager.setup(secrets)

    kernel = VeraKernel.get_instance()
    await kernel.initialise(bus=bus, vfs=vfs)
    kernel.set_auth_manager(auth_manager)
    kernel.set_security(security)

    # Load middleware chain from user config (falls back to built-in defaults)
    kernel.load_middlewares_from_config()

    if plugins_dir:
        kernel._plugins_dir = plugins_dir
    kernel.load_all_plugins()

    from core.api import WebSocketManager
    ws_manager = WebSocketManager()

    factory = VeraDepsFactory(kernel, bus, vfs, secrets, security, ws_manager=ws_manager)

    # Store on kernel so the API auth dependency can reach them without globals
    kernel._deps_factory = factory
    kernel._ws_manager = ws_manager

    return kernel, bus, vfs, secrets, security, tracer, factory
