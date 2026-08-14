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
    INVENTORY_WRITEOFF = "inventory.writeoff"
    INVENTORY_COUNT = "inventory.count"
    INVENTORY_TRANSFER = "inventory.transfer"
    INVENTORY_MOVEMENT_READ = "inventory.movement.read"
    PURCHASING_READ = "purchasing.read"
    PURCHASING_WRITE = "purchasing.write"
    PURCHASING_CREATE = "purchasing.create"
    PURCHASING_UPDATE = "purchasing.update"
    PURCHASING_RECEIVE = "purchasing.receive"
    PURCHASING_CANCEL = "purchasing.cancel"
    PURCHASING_RETURN = "purchasing.return"
    MENU_READ = "menu.read"
    MENU_WRITE = "menu.write"
    MENU_PRODUCT_CREATE = "menu.product.create"
    MENU_PRODUCT_UPDATE = "menu.product.update"
    MENU_PRODUCT_ARCHIVE = "menu.product.archive"
    MENU_RECIPE_READ = "menu.recipe.read"
    MENU_RECIPE_WRITE = "menu.recipe.write"
    MENU_PRICE_WRITE = "menu.price.write"
    MENU_MODIFIER_WRITE = "menu.modifier.write"
    SALES_READ = "sales.read"
    SALES_READ_OWN = "sales.read_own"
    SALES_CREATE = "sales.create"
    SALES_REFUND = "sales.refund"
    SALES_REGISTER_MANAGE = "sales.register.manage"
    SALES_SHIFT_MANAGE = "sales.shift.manage"
    SALES_CANCEL = "sales.cancel"
    PAYMENTS_READ = "payments.read"
    PAYMENTS_CREATE = "payments.create"
    PAYMENTS_REFUND = "payments.refund"
    PAYMENTS_TERMINAL_MANAGE = "payments.terminal.manage"
    FINANCE_READ = "finance.read"
    FINANCE_WRITE = "finance.write"
    ANALYTICS_READ = "analytics.read"
    INTEGRATIONS_READ = "integrations.read"
    INTEGRATIONS_WRITE = "integrations.write"
    POS_DEVICE_MANAGE = "pos.device.manage"
    FISCAL_READ = "fiscal.read"
    FISCAL_WRITE = "fiscal.write"
    ONBOARDING_READ = "onboarding.read"
    ONBOARDING_WRITE = "onboarding.write"
    MENU_IMPORT = "menu.import"
    PROMOTIONS_READ = "promotions.read"
    PROMOTIONS_WRITE = "promotions.write"
    DISCOUNTS_APPLY = "discounts.apply"
    DISCOUNTS_OVERRIDE = "discounts.override"
    CUSTOMERS_READ = "customers.read"
    CUSTOMERS_WRITE = "customers.write"
    LOYALTY_READ = "loyalty.read"
    LOYALTY_ADJUST = "loyalty.adjust"
    LOYALTY_CONFIGURE = "loyalty.configure"
    LOYALTY_REDEEM = "loyalty.redeem"
    CASH_DRAWER_USE = "cash.drawer.use"
    CASH_DRAWER_ADJUST = "cash.drawer.adjust"
    CASH_DRAWER_CLOSE = "cash.drawer.close"
    CASH_DRAWER_VIEW_EXPECTED = "cash.drawer.view_expected"
    CASH_DRAWER_APPROVE_VARIANCE = "cash.drawer.approve_variance"
    CASH_DRAWER_REPORT = "cash.drawer.report"
    KITCHEN_READ = "kitchen.read"
    KITCHEN_WORK = "kitchen.work"
    KITCHEN_EXPO = "kitchen.expo"
    KITCHEN_MANAGE = "kitchen.manage"
    KITCHEN_REPORT = "kitchen.report"


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
            Permission.INVENTORY_WRITEOFF,
            Permission.INVENTORY_COUNT,
            Permission.INVENTORY_TRANSFER,
            Permission.INVENTORY_MOVEMENT_READ,
            Permission.PURCHASING_READ,
            Permission.PURCHASING_WRITE,
            Permission.PURCHASING_CREATE,
            Permission.PURCHASING_UPDATE,
            Permission.PURCHASING_RECEIVE,
            Permission.PURCHASING_CANCEL,
            Permission.PURCHASING_RETURN,
            Permission.MENU_READ,
            Permission.MENU_WRITE,
            Permission.MENU_PRODUCT_CREATE,
            Permission.MENU_PRODUCT_UPDATE,
            Permission.MENU_PRODUCT_ARCHIVE,
            Permission.MENU_RECIPE_READ,
            Permission.MENU_RECIPE_WRITE,
            Permission.MENU_PRICE_WRITE,
            Permission.MENU_MODIFIER_WRITE,
            Permission.SALES_READ,
            Permission.SALES_CREATE,
            Permission.SALES_REFUND,
            Permission.SALES_REGISTER_MANAGE,
            Permission.SALES_SHIFT_MANAGE,
            Permission.SALES_CANCEL,
            Permission.PAYMENTS_READ,
            Permission.PAYMENTS_CREATE,
            Permission.PAYMENTS_REFUND,
            Permission.PAYMENTS_TERMINAL_MANAGE,
            Permission.FINANCE_READ,
            Permission.FINANCE_WRITE,
            Permission.ANALYTICS_READ,
            Permission.INTEGRATIONS_READ,
            Permission.INTEGRATIONS_WRITE,
            Permission.POS_DEVICE_MANAGE,
            Permission.FISCAL_READ,
            Permission.FISCAL_WRITE,
            Permission.ONBOARDING_READ,
            Permission.ONBOARDING_WRITE,
            Permission.MENU_IMPORT,
            Permission.PROMOTIONS_READ,
            Permission.PROMOTIONS_WRITE,
            Permission.DISCOUNTS_APPLY,
            Permission.DISCOUNTS_OVERRIDE,
            Permission.CUSTOMERS_READ,
            Permission.CUSTOMERS_WRITE,
            Permission.LOYALTY_READ,
            Permission.LOYALTY_ADJUST,
            Permission.LOYALTY_CONFIGURE,
            Permission.LOYALTY_REDEEM,
            Permission.CASH_DRAWER_USE,
            Permission.CASH_DRAWER_ADJUST,
            Permission.CASH_DRAWER_CLOSE,
            Permission.CASH_DRAWER_VIEW_EXPECTED,
            Permission.CASH_DRAWER_APPROVE_VARIANCE,
            Permission.CASH_DRAWER_REPORT,
            Permission.KITCHEN_READ,
            Permission.KITCHEN_WORK,
            Permission.KITCHEN_EXPO,
            Permission.KITCHEN_MANAGE,
            Permission.KITCHEN_REPORT,
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
            Permission.INVENTORY_WRITEOFF,
            Permission.INVENTORY_COUNT,
            Permission.INVENTORY_TRANSFER,
            Permission.INVENTORY_MOVEMENT_READ,
            Permission.PURCHASING_READ,
            Permission.PURCHASING_WRITE,
            Permission.PURCHASING_CREATE,
            Permission.PURCHASING_UPDATE,
            Permission.PURCHASING_RECEIVE,
            Permission.PURCHASING_RETURN,
            Permission.MENU_READ,
            Permission.MENU_WRITE,
            Permission.MENU_PRODUCT_CREATE,
            Permission.MENU_PRODUCT_UPDATE,
            Permission.MENU_PRODUCT_ARCHIVE,
            Permission.MENU_RECIPE_READ,
            Permission.MENU_RECIPE_WRITE,
            Permission.MENU_PRICE_WRITE,
            Permission.MENU_MODIFIER_WRITE,
            Permission.SALES_READ,
            Permission.SALES_REFUND,
            Permission.SALES_REGISTER_MANAGE,
            Permission.SALES_SHIFT_MANAGE,
            Permission.SALES_CANCEL,
            Permission.PAYMENTS_READ,
            Permission.PAYMENTS_CREATE,
            Permission.PAYMENTS_REFUND,
            Permission.ANALYTICS_READ,
            Permission.INTEGRATIONS_READ,
            Permission.POS_DEVICE_MANAGE,
            Permission.FISCAL_READ,
            Permission.ONBOARDING_READ,
            Permission.MENU_IMPORT,
            Permission.PROMOTIONS_READ,
            Permission.DISCOUNTS_APPLY,
            Permission.DISCOUNTS_OVERRIDE,
            Permission.CUSTOMERS_READ,
            Permission.CUSTOMERS_WRITE,
            Permission.LOYALTY_READ,
            Permission.LOYALTY_ADJUST,
            Permission.LOYALTY_REDEEM,
            Permission.CASH_DRAWER_USE,
            Permission.CASH_DRAWER_ADJUST,
            Permission.CASH_DRAWER_CLOSE,
            Permission.CASH_DRAWER_VIEW_EXPECTED,
            Permission.CASH_DRAWER_APPROVE_VARIANCE,
            Permission.CASH_DRAWER_REPORT,
            Permission.KITCHEN_READ,
            Permission.KITCHEN_WORK,
            Permission.KITCHEN_EXPO,
            Permission.KITCHEN_MANAGE,
            Permission.KITCHEN_REPORT,
        }
    ),
    MembershipRole.ACCOUNTANT: frozenset(
        {
            Permission.ORGANIZATION_READ,
            Permission.INVENTORY_READ,
            Permission.INVENTORY_MOVEMENT_READ,
            Permission.SALES_READ,
            Permission.PAYMENTS_READ,
            Permission.PURCHASING_READ,
            Permission.MENU_READ,
            Permission.FINANCE_READ,
            Permission.FINANCE_WRITE,
            Permission.ANALYTICS_READ,
            Permission.INTEGRATIONS_READ,
            Permission.FISCAL_READ,
            Permission.FISCAL_WRITE,
            Permission.PROMOTIONS_READ,
            Permission.CUSTOMERS_READ,
            Permission.LOYALTY_READ,
            Permission.CASH_DRAWER_VIEW_EXPECTED,
            Permission.CASH_DRAWER_REPORT,
            Permission.KITCHEN_REPORT,
        }
    ),
    MembershipRole.CASHIER: frozenset(
        {
            Permission.ORGANIZATION_READ,
            Permission.MENU_READ,
            Permission.SALES_CREATE,
            Permission.SALES_READ_OWN,
            Permission.SALES_SHIFT_MANAGE,
            Permission.PAYMENTS_CREATE,
            Permission.DISCOUNTS_APPLY,
            Permission.CUSTOMERS_READ,
            Permission.CUSTOMERS_WRITE,
            Permission.LOYALTY_READ,
            Permission.LOYALTY_REDEEM,
            Permission.CASH_DRAWER_USE,
            Permission.CASH_DRAWER_CLOSE,
            Permission.KITCHEN_READ,
        }
    ),
    MembershipRole.BARISTA: frozenset(
        {
            Permission.ORGANIZATION_READ,
            Permission.MENU_READ,
            Permission.SALES_CREATE,
            Permission.SALES_READ_OWN,
            Permission.SALES_SHIFT_MANAGE,
            Permission.INVENTORY_READ_LIMITED,
            Permission.CUSTOMERS_READ,
            Permission.CUSTOMERS_WRITE,
            Permission.LOYALTY_READ,
            Permission.CASH_DRAWER_USE,
            Permission.CASH_DRAWER_CLOSE,
            Permission.KITCHEN_READ,
            Permission.KITCHEN_WORK,
        }
    ),
}


def permissions_for(role: MembershipRole) -> frozenset[Permission]:
    return ROLE_PERMISSIONS[role]
