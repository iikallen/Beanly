from beanly.modules.organizations.domain.enums import MembershipRole
from beanly.modules.organizations.domain.permissions import Permission, permissions_for


def test_role_permission_matrix_matches_current_contract() -> None:
    expected = {
        MembershipRole.OWNER: frozenset(Permission),
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

    assert set(expected) == set(MembershipRole)
    for role, permissions in expected.items():
        assert permissions_for(role) == permissions

    assert Permission.ORGANIZATION_TRANSFER_OWNERSHIP in permissions_for(MembershipRole.OWNER)
    assert Permission.ORGANIZATION_TRANSFER_OWNERSHIP not in permissions_for(MembershipRole.ADMIN)
    for role in (MembershipRole.OWNER, MembershipRole.ADMIN, MembershipRole.MANAGER):
        assert Permission.POS_DEVICE_MANAGE in permissions_for(role)
    for role in (
        MembershipRole.ACCOUNTANT,
        MembershipRole.CASHIER,
        MembershipRole.BARISTA,
    ):
        assert Permission.POS_DEVICE_MANAGE not in permissions_for(role)
    for role in (MembershipRole.CASHIER, MembershipRole.BARISTA):
        assert Permission.SALES_CREATE in permissions_for(role)
    for role in (MembershipRole.OWNER, MembershipRole.ADMIN, MembershipRole.ACCOUNTANT):
        assert Permission.FISCAL_WRITE in permissions_for(role)
    assert Permission.FISCAL_READ in permissions_for(MembershipRole.MANAGER)
    assert Permission.FISCAL_WRITE not in permissions_for(MembershipRole.MANAGER)
    for role in (MembershipRole.CASHIER, MembershipRole.BARISTA):
        assert Permission.FISCAL_READ not in permissions_for(role)
        assert Permission.FISCAL_WRITE not in permissions_for(role)
    for role in (MembershipRole.OWNER, MembershipRole.ADMIN):
        assert Permission.PAYMENTS_TERMINAL_MANAGE in permissions_for(role)
    for role in (
        MembershipRole.MANAGER,
        MembershipRole.ACCOUNTANT,
        MembershipRole.CASHIER,
        MembershipRole.BARISTA,
    ):
        assert Permission.PAYMENTS_TERMINAL_MANAGE not in permissions_for(role)
    for role in (MembershipRole.OWNER, MembershipRole.ADMIN):
        assert {
            Permission.ONBOARDING_READ,
            Permission.ONBOARDING_WRITE,
            Permission.MENU_IMPORT,
        } <= permissions_for(role)
    assert {
        Permission.ONBOARDING_READ,
        Permission.MENU_IMPORT,
    } <= permissions_for(MembershipRole.MANAGER)
    assert Permission.ONBOARDING_WRITE not in permissions_for(MembershipRole.MANAGER)
    for role in (
        MembershipRole.ACCOUNTANT,
        MembershipRole.CASHIER,
        MembershipRole.BARISTA,
    ):
        assert {
            Permission.ONBOARDING_READ,
            Permission.ONBOARDING_WRITE,
            Permission.MENU_IMPORT,
        }.isdisjoint(permissions_for(role))
