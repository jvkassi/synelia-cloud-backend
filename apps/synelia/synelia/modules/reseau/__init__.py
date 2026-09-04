from synelia.modules.reseau.router import (
    router_groupes,
    router_ips,
    router_lb,
    router_reseaux,
    router_vpn,
)

routers = [router_reseaux, router_ips, router_groupes, router_lb, router_vpn]

__all__ = ["routers"]
