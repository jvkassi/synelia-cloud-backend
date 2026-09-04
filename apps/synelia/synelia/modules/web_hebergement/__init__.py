from synelia.modules.web_hebergement.router_bases import router as router_bases
from synelia.modules.web_hebergement.router_hebergements import router as router_hebergements
from synelia.modules.web_hebergement.router_sites import router as router_sites

routers = [router_hebergements, router_sites, router_bases]
router = router_hebergements

__all__ = ["router", "routers"]
