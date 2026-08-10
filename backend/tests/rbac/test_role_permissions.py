from beanly.modules.organizations.domain.enums import MembershipRole
from beanly.modules.organizations.domain.permissions import Permission, permissions_for


def test_role_permission_matrix_matches_stage_three_contract() -> None:
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
                Permission.SALES_REGISTER_MANAGE,
                Permission.SALES_SHIFT_MANAGE,
                Permission.SALES_CANCEL,
                Permission.PAYMENTS_READ,
                Permission.PAYMENTS_CREATE,
                Permission.PAYMENTS_REFUND,
                Permission.ANALYTICS_READ,
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
            }
        ),
    }

    assert set(expected) == set(MembershipRole)
    for role, permissions in expected.items():
        assert permissions_for(role) == permissions

    assert Permission.ORGANIZATION_TRANSFER_OWNERSHIP in permissions_for(MembershipRole.OWNER)
    assert Permission.ORGANIZATION_TRANSFER_OWNERSHIP not in permissions_for(MembershipRole.ADMIN)
