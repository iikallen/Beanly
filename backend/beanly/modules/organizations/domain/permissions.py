from enum import StrEnum

from beanly.modules.organizations.domain.enums import MembershipRole


class Permission(StrEnum):
    ORGANIZATION_READ = "organization.read"
    ORGANIZATION_UPDATE = "organization.update"
    ORGANIZATION_TRANSFER_OWNERSHIP = "organization.transfer_ownership"
    LOCATION_READ = "location.read"
    LOCATION_CREATE = "location.create"
    LOCATION_UPDATE = "location.update"
    TEAM_READ = "team.read"
    TEAM_INVITE = "team.invite"
    TEAM_UPDATE = "team.update"
    TEAM_REMOVE = "team.remove"
    INVENTORY_READ = "inventory.read"
    INVENTORY_READ_LIMITED = "inventory.read_limited"
    INVENTORY_WRITE = "inventory.write"
    INVENTORY_ADJUST = "inventory.adjust"
    PURCHASING_READ = "purchasing.read"
    PURCHASING_WRITE = "purchasing.write"
    PURCHASING_CREATE = "purchasing.create"
    PURCHASING_UPDATE = "purchasing.update"
    PURCHASING_RECEIVE = "purchasing.receive"
    PURCHASING_CANCEL = "purchasing.cancel"
    MENU_READ = "menu.read"
    MENU_WRITE = "menu.write"
    MENU_PRODUCT_CREATE = "menu.product.create"
    MENU_PRODUCT_UPDATE = "menu.product.update"
    MENU_PRODUCT_ARCHIVE = "menu.product.archive"
    MENU_RECIPE_READ = "menu.recipe.read"
    MENU_RECIPE_WRITE = "menu.recipe.write"
    MENU_PRICE_WRITE = "menu.price.write"
    SALES_READ = "sales.read"
    SALES_READ_OWN = "sales.read_own"
    SALES_CREATE = "sales.create"
    SALES_REFUND = "sales.refund"
    PAYMENTS_READ = "payments.read"
    PAYMENTS_CREATE = "payments.create"
    PAYMENTS_REFUND = "payments.refund"
    FINANCE_READ = "finance.read"
    FINANCE_WRITE = "finance.write"
    ANALYTICS_READ = "analytics.read"


_ALL = frozenset(Permission)

ROLE_PERMISSIONS: dict[MembershipRole, frozenset[Permission]] = {
    MembershipRole.OWNER: _ALL,
    MembershipRole.ADMIN: frozenset(
        {
            Permission.ORGANIZATION_READ,
            Permission.LOCATION_READ,
            Permission.LOCATION_CREATE,
            Permission.LOCATION_UPDATE,
            Permission.TEAM_READ,
            Permission.TEAM_INVITE,
            Permission.TEAM_UPDATE,
            Permission.TEAM_REMOVE,
            Permission.INVENTORY_READ,
            Permission.INVENTORY_WRITE,
            Permission.INVENTORY_ADJUST,
            Permission.PURCHASING_READ,
            Permission.PURCHASING_WRITE,
            Permission.PURCHASING_CREATE,
            Permission.PURCHASING_UPDATE,
            Permission.PURCHASING_RECEIVE,
            Permission.PURCHASING_CANCEL,
            Permission.MENU_READ,
            Permission.MENU_WRITE,
            Permission.MENU_PRODUCT_CREATE,
            Permission.MENU_PRODUCT_UPDATE,
            Permission.MENU_PRODUCT_ARCHIVE,
            Permission.MENU_RECIPE_READ,
            Permission.MENU_RECIPE_WRITE,
            Permission.MENU_PRICE_WRITE,
            Permission.SALES_READ,
            Permission.SALES_CREATE,
            Permission.SALES_REFUND,
            Permission.PAYMENTS_READ,
            Permission.PAYMENTS_CREATE,
            Permission.PAYMENTS_REFUND,
            Permission.FINANCE_READ,
            Permission.FINANCE_WRITE,
            Permission.ANALYTICS_READ,
        }
    ),
    MembershipRole.MANAGER: frozenset(
        {
            Permission.ORGANIZATION_READ,
            Permission.LOCATION_READ,
            Permission.TEAM_READ,
            Permission.INVENTORY_READ,
            Permission.INVENTORY_WRITE,
            Permission.INVENTORY_ADJUST,
            Permission.PURCHASING_READ,
            Permission.PURCHASING_WRITE,
            Permission.PURCHASING_CREATE,
            Permission.PURCHASING_UPDATE,
            Permission.PURCHASING_RECEIVE,
            Permission.MENU_READ,
            Permission.MENU_WRITE,
            Permission.MENU_PRODUCT_CREATE,
            Permission.MENU_PRODUCT_UPDATE,
            Permission.MENU_PRODUCT_ARCHIVE,
            Permission.MENU_RECIPE_READ,
            Permission.MENU_RECIPE_WRITE,
            Permission.MENU_PRICE_WRITE,
            Permission.SALES_READ,
            Permission.ANALYTICS_READ,
        }
    ),
    MembershipRole.ACCOUNTANT: frozenset(
        {
            Permission.ORGANIZATION_READ,
            Permission.INVENTORY_READ,
            Permission.SALES_READ,
            Permission.PAYMENTS_READ,
            Permission.PURCHASING_READ,
            Permission.MENU_READ,
            Permission.FINANCE_READ,
            Permission.FINANCE_WRITE,
            Permission.ANALYTICS_READ,
        }
    ),
    MembershipRole.CASHIER: frozenset(
        {
            Permission.ORGANIZATION_READ,
            Permission.MENU_READ,
            Permission.SALES_CREATE,
            Permission.SALES_READ_OWN,
            Permission.PAYMENTS_CREATE,
        }
    ),
    MembershipRole.BARISTA: frozenset(
        {
            Permission.ORGANIZATION_READ,
            Permission.MENU_READ,
            Permission.SALES_CREATE,
            Permission.INVENTORY_READ_LIMITED,
        }
    ),
}


def permissions_for(role: MembershipRole) -> frozenset[Permission]:
    return ROLE_PERMISSIONS[role]
