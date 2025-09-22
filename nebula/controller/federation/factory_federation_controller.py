from nebula.controller.federation.federation_controller import FederationController

def federation_controller_factory(mode: str, wa_controller_url: str, logger) -> FederationController:
    from nebula.controller.federation.controllers.docker_federation_controller import DockerFederationController
    from nebula.controller.federation.controllers.processes_federation_controller import ProcessesFederationController
    from nebula.controller.federation.controllers.physicall_federation_controller import PhysicalFederationController
    
    if mode == "docker":
        return DockerFederationController(wa_controller_url, logger)
    elif mode == "physical":
        return PhysicalFederationController(wa_controller_url, logger)
    elif mode == "process":
        return ProcessesFederationController(wa_controller_url, logger)
    else:
        raise ValueError("Unknown federation mode")