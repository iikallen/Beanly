from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError

from beanly.modules.menu.api.dependencies import (
    CustomizationServiceDep,
    MenuModifierReadDep,
    MenuModifierWriteDep,
    MenuPriceWriteDep,
    MenuProductArchiveDep,
    MenuProductCreateDep,
    MenuProductUpdateDep,
    MenuReadDep,
    MenuRecipeReadDep,
    MenuRecipeWriteDep,
    MenuServiceDep,
)
from beanly.modules.menu.api.schemas import (
    BatchCostsResponse,
    BatchCostVariantResponse,
    CategoryPatchRequest,
    CategoryRequest,
    CategoryResponse,
    CustomizationPreviewRequest,
    CustomizationPreviewResponse,
    MenuCategoryResponse,
    MenuResponse,
    ModifierComponentsRequest,
    ModifierGroupPatchRequest,
    ModifierGroupRequest,
    ModifierGroupResponse,
    ModifierLocationRequest,
    ModifierLocationResponse,
    ModifierOptionPatchRequest,
    ModifierOptionRequest,
    ModifierOptionResponse,
    ModifierPriceRequest,
    ModifierPriceResponse,
    ProductCreateRequest,
    ProductLocationRequest,
    ProductLocationResponse,
    ProductPatchRequest,
    ProductResponse,
    RecipeCostResponse,
    RecipeRequest,
    RecipeResponse,
    VariantCreateRequest,
    VariantPatchRequest,
    VariantPriceRequest,
    VariantPriceResponse,
    VariantResponse,
)
from beanly.modules.menu.application.commands import (
    ModifierComponentInput,
    RecipeComponentInput,
    VariantInput,
)
from beanly.modules.menu.domain.enums import ProductStatus
from beanly.modules.menu.domain.exceptions import (
    InvalidMenuOperation,
    InvalidModifierRecipe,
    InvalidModifierSelection,
    MenuConflict,
    MenuNotFound,
)
from beanly.modules.organizations.domain.exceptions import OrganizationAccessDenied
from beanly.modules.organizations.domain.permissions import Permission

router = APIRouter(prefix="/menu", tags=["menu"])


@router.post("/categories", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(
    payload: CategoryRequest, context: MenuProductCreateDep, service: MenuServiceDep
) -> CategoryResponse:
    try:
        value = await service.create_category(context, payload.name, payload.sort_order)
    except Exception as exc:
        raise _http_error(exc) from exc
    return CategoryResponse.from_entity(value)


@router.get("/categories", response_model=list[CategoryResponse])
async def list_categories(context: MenuReadDep, service: MenuServiceDep) -> list[CategoryResponse]:
    return [CategoryResponse.from_entity(value) for value in await service.list_categories(context)]


@router.patch("/categories/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: UUID,
    payload: CategoryPatchRequest,
    context: MenuProductUpdateDep,
    service: MenuServiceDep,
) -> CategoryResponse:
    if not payload.model_fields_set:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No fields to update")
    try:
        value = await service.update_category(
            context,
            category_id,
            name=payload.name,
            sort_order=payload.sort_order,
            is_active=None,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return CategoryResponse.from_entity(value)


@router.post("/categories/{category_id}/archive", response_model=CategoryResponse)
async def archive_category(
    category_id: UUID, context: MenuProductArchiveDep, service: MenuServiceDep
) -> CategoryResponse:
    try:
        value = await service.archive_category(context, category_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return CategoryResponse.from_entity(value)


@router.post("/products", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreateRequest,
    context: MenuProductCreateDep,
    service: MenuServiceDep,
) -> ProductResponse:
    variant = payload.default_variant or VariantCreateRequest(is_default=True)
    if variant.base_price_minor and not context.permissions.intersection(
        {Permission.MENU_PRICE_WRITE, Permission.MENU_WRITE}
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
    try:
        value = await service.create_product(
            context,
            payload.category_id,
            payload.name,
            payload.description,
            payload.image_url,
            VariantInput(variant.name, variant.sku, variant.base_price_minor),
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return ProductResponse.from_entity(value)


@router.get("/products", response_model=list[ProductResponse])
async def list_products(
    context: MenuReadDep,
    service: MenuServiceDep,
    category_id: UUID | None = None,
    status_filter: Annotated[ProductStatus | None, Query(alias="status")] = None,
    search: str | None = None,
    location_id: UUID | None = None,
) -> list[ProductResponse]:
    try:
        values = await service.list_products(
            context, category_id, status_filter, search, location_id
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return [ProductResponse.from_entity(value) for value in values]


@router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: UUID,
    context: MenuReadDep,
    service: MenuServiceDep,
    location_id: UUID | None = None,
) -> ProductResponse:
    try:
        value = await service.get_product(context, product_id, location_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return ProductResponse.from_entity(value)


@router.patch("/products/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: UUID,
    payload: ProductPatchRequest,
    context: MenuProductUpdateDep,
    service: MenuServiceDep,
) -> ProductResponse:
    fields = payload.model_fields_set
    if not fields:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No fields to update")
    try:
        value = await service.update_product(
            context,
            product_id,
            category_id=payload.category_id,
            name=payload.name,
            description=payload.description,
            description_set="description" in fields,
            image_url=payload.image_url,
            image_url_set="image_url" in fields,
            status=payload.status,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return ProductResponse.from_entity(value)


@router.post("/products/{product_id}/archive", response_model=ProductResponse)
async def archive_product(
    product_id: UUID, context: MenuProductArchiveDep, service: MenuServiceDep
) -> ProductResponse:
    try:
        value = await service.archive_product(context, product_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return ProductResponse.from_entity(value)


@router.post(
    "/products/{product_id}/variants",
    response_model=VariantResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_variant(
    product_id: UUID,
    payload: VariantCreateRequest,
    context: MenuProductCreateDep,
    service: MenuServiceDep,
) -> VariantResponse:
    if payload.base_price_minor and not context.permissions.intersection(
        {Permission.MENU_PRICE_WRITE, Permission.MENU_WRITE}
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
    try:
        value = await service.create_variant(
            context,
            product_id,
            VariantInput(payload.name, payload.sku, payload.base_price_minor),
            payload.is_default,
            payload.sort_order,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return VariantResponse.from_entity(value)


@router.patch("/variants/{variant_id}", response_model=VariantResponse)
async def update_variant(
    variant_id: UUID,
    payload: VariantPatchRequest,
    context: MenuProductUpdateDep,
    service: MenuServiceDep,
) -> VariantResponse:
    if not payload.model_fields_set:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No fields to update")
    if "base_price_minor" in payload.model_fields_set and not context.permissions.intersection(
        {Permission.MENU_PRICE_WRITE, Permission.MENU_WRITE}
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
    try:
        value = await service.update_variant(
            context,
            variant_id,
            name=payload.name,
            sku=payload.sku,
            sku_set="sku" in payload.model_fields_set,
            base_price_minor=payload.base_price_minor,
            is_default=payload.is_default,
            sort_order=payload.sort_order,
            status=payload.status,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return VariantResponse.from_entity(value)


@router.post("/variants/{variant_id}/archive", response_model=VariantResponse)
async def archive_variant(
    variant_id: UUID, context: MenuProductArchiveDep, service: MenuServiceDep
) -> VariantResponse:
    try:
        value = await service.archive_variant(context, variant_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return VariantResponse.from_entity(value)


@router.put("/variants/{variant_id}/recipe", response_model=RecipeResponse)
async def set_recipe(
    variant_id: UUID,
    payload: RecipeRequest,
    context: MenuRecipeWriteDep,
    service: MenuServiceDep,
) -> RecipeResponse:
    inputs = tuple(
        RecipeComponentInput(value.inventory_item_id, value.quantity, value.unit, value.sort_order)
        for value in payload.components
    )
    try:
        value = await service.set_recipe(
            context, variant_id, payload.name, payload.yield_quantity, inputs
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return RecipeResponse.from_detail(value)


@router.get("/variants/{variant_id}/recipe", response_model=RecipeResponse)
async def get_recipe(
    variant_id: UUID, context: MenuRecipeReadDep, service: MenuServiceDep
) -> RecipeResponse:
    try:
        value = await service.get_recipe(context, variant_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return RecipeResponse.from_detail(value)


@router.get("/variants/{variant_id}/cost", response_model=RecipeCostResponse)
async def get_cost(
    variant_id: UUID,
    warehouse_id: UUID,
    context: MenuRecipeReadDep,
    service: MenuServiceDep,
    location_id: UUID | None = None,
) -> RecipeCostResponse:
    try:
        value = await service.calculate_cost(context, variant_id, warehouse_id, location_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return RecipeCostResponse.from_entity(value)


@router.get("/costs", response_model=BatchCostsResponse)
async def get_costs(
    warehouse_id: UUID,
    context: MenuRecipeReadDep,
    service: MenuServiceDep,
    location_id: UUID | None = None,
) -> BatchCostsResponse:
    try:
        values = await service.calculate_costs(context, warehouse_id, location_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return BatchCostsResponse(
        warehouse_id=warehouse_id,
        variants=[BatchCostVariantResponse.from_entity(value) for value in values],
    )


@router.put("/variants/{variant_id}/prices/{location_id}", response_model=VariantPriceResponse)
async def set_variant_price(
    variant_id: UUID,
    location_id: UUID,
    payload: VariantPriceRequest,
    context: MenuPriceWriteDep,
    service: MenuServiceDep,
) -> VariantPriceResponse:
    try:
        value = await service.set_variant_price(
            context, variant_id, location_id, payload.price_minor
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return VariantPriceResponse.from_entity(variant_id, location_id, value)


@router.put(
    "/products/{product_id}/locations/{location_id}",
    response_model=ProductLocationResponse,
)
async def set_product_location(
    product_id: UUID,
    location_id: UUID,
    payload: ProductLocationRequest,
    context: MenuProductUpdateDep,
    service: MenuServiceDep,
) -> ProductLocationResponse:
    try:
        value = await service.set_product_location(
            context,
            product_id,
            location_id,
            payload.is_available,
            payload.is_visible,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return ProductLocationResponse.from_entity(value)


@router.post(
    "/variants/{variant_id}/modifier-groups",
    response_model=ModifierGroupResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_modifier_group(
    variant_id: UUID,
    payload: ModifierGroupRequest,
    context: MenuModifierWriteDep,
    service: MenuServiceDep,
) -> ModifierGroupResponse:
    try:
        value = await service.create_modifier_group(
            context,
            variant_id,
            payload.name,
            payload.selection_type,
            payload.min_selections,
            payload.max_selections,
            payload.sort_order,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return ModifierGroupResponse.from_entity(value)


@router.get("/variants/{variant_id}/modifier-groups", response_model=list[ModifierGroupResponse])
async def list_modifier_groups(
    variant_id: UUID,
    context: MenuModifierReadDep,
    service: MenuServiceDep,
    location_id: UUID | None = None,
) -> list[ModifierGroupResponse]:
    try:
        values = await service.list_modifier_groups(context, variant_id, location_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return [ModifierGroupResponse.from_entity(value) for value in values]


@router.patch("/modifier-groups/{group_id}", response_model=ModifierGroupResponse)
async def update_modifier_group(
    group_id: UUID,
    payload: ModifierGroupPatchRequest,
    context: MenuModifierWriteDep,
    service: MenuServiceDep,
) -> ModifierGroupResponse:
    if not payload.model_fields_set:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No fields to update")
    try:
        value = await service.update_modifier_group(
            context,
            group_id,
            name=payload.name,
            selection_type=payload.selection_type,
            min_selections=payload.min_selections,
            max_selections=payload.max_selections,
            sort_order=payload.sort_order,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return ModifierGroupResponse.from_entity(value)


@router.post("/modifier-groups/{group_id}/archive", response_model=ModifierGroupResponse)
async def archive_modifier_group(
    group_id: UUID, context: MenuModifierWriteDep, service: MenuServiceDep
) -> ModifierGroupResponse:
    try:
        value = await service.archive_modifier_group(context, group_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return ModifierGroupResponse.from_entity(value)


@router.post(
    "/modifier-groups/{group_id}/options",
    response_model=ModifierOptionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_modifier_option(
    group_id: UUID,
    payload: ModifierOptionRequest,
    context: MenuModifierWriteDep,
    service: MenuServiceDep,
) -> ModifierOptionResponse:
    try:
        value = await service.create_modifier_option(
            context,
            group_id,
            payload.name,
            payload.base_price_delta_minor,
            payload.is_default,
            payload.sort_order,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return ModifierOptionResponse.from_entity(value)


@router.patch("/modifier-options/{option_id}", response_model=ModifierOptionResponse)
async def update_modifier_option(
    option_id: UUID,
    payload: ModifierOptionPatchRequest,
    context: MenuModifierWriteDep,
    service: MenuServiceDep,
) -> ModifierOptionResponse:
    if not payload.model_fields_set:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No fields to update")
    try:
        value = await service.update_modifier_option(
            context,
            option_id,
            name=payload.name,
            base_price_delta_minor=payload.base_price_delta_minor,
            is_default=payload.is_default,
            sort_order=payload.sort_order,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return ModifierOptionResponse.from_entity(value)


@router.post("/modifier-options/{option_id}/archive", response_model=ModifierOptionResponse)
async def archive_modifier_option(
    option_id: UUID, context: MenuModifierWriteDep, service: MenuServiceDep
) -> ModifierOptionResponse:
    try:
        value = await service.archive_modifier_option(context, option_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return ModifierOptionResponse.from_entity(value)


@router.put("/modifier-options/{option_id}/components", response_model=ModifierOptionResponse)
async def replace_modifier_components(
    option_id: UUID,
    payload: ModifierComponentsRequest,
    context: MenuModifierWriteDep,
    service: MenuServiceDep,
) -> ModifierOptionResponse:
    inputs = tuple(
        ModifierComponentInput(
            value.inventory_item_id,
            value.quantity_delta,
            value.unit,
            value.sort_order,
        )
        for value in payload.components
    )
    try:
        value = await service.replace_modifier_components(context, option_id, inputs)
    except Exception as exc:
        raise _http_error(exc) from exc
    return ModifierOptionResponse.from_entity(value)


@router.put(
    "/modifier-options/{option_id}/prices/{location_id}",
    response_model=ModifierPriceResponse,
)
async def set_modifier_option_price(
    option_id: UUID,
    location_id: UUID,
    payload: ModifierPriceRequest,
    context: MenuModifierWriteDep,
    service: MenuServiceDep,
) -> ModifierPriceResponse:
    try:
        value = await service.set_modifier_option_price(
            context, option_id, location_id, payload.price_delta_minor
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return ModifierPriceResponse.from_entity(option_id, location_id, value)


@router.delete(
    "/modifier-options/{option_id}/prices/{location_id}",
    response_model=ModifierPriceResponse,
)
async def delete_modifier_option_price(
    option_id: UUID,
    location_id: UUID,
    context: MenuModifierWriteDep,
    service: MenuServiceDep,
) -> ModifierPriceResponse:
    try:
        await service.delete_modifier_option_price(context, option_id, location_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return ModifierPriceResponse.from_entity(option_id, location_id, None)


@router.put(
    "/modifier-options/{option_id}/locations/{location_id}",
    response_model=ModifierLocationResponse,
)
async def set_modifier_option_location(
    option_id: UUID,
    location_id: UUID,
    payload: ModifierLocationRequest,
    context: MenuModifierWriteDep,
    service: MenuServiceDep,
) -> ModifierLocationResponse:
    try:
        value = await service.set_modifier_option_location(
            context, option_id, location_id, payload.is_available
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return ModifierLocationResponse.from_entity(value)


@router.post(
    "/variants/{variant_id}/customization-preview",
    response_model=CustomizationPreviewResponse,
)
async def customization_preview(
    variant_id: UUID,
    warehouse_id: UUID,
    location_id: UUID,
    payload: CustomizationPreviewRequest,
    context: MenuModifierReadDep,
    service: CustomizationServiceDep,
) -> CustomizationPreviewResponse:
    try:
        value = await service.preview(
            context,
            variant_id,
            warehouse_id,
            location_id,
            tuple(payload.selected_option_ids),
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return CustomizationPreviewResponse.from_entity(value)


@router.get("", response_model=MenuResponse)
async def get_menu(
    location_id: UUID, context: MenuReadDep, service: MenuServiceDep
) -> MenuResponse:
    try:
        products = await service.get_menu(context, location_id)
        categories = [value for value in await service.list_categories(context) if value.is_active]
    except Exception as exc:
        raise _http_error(exc) from exc
    return MenuResponse(
        location_id=location_id,
        categories=[
            MenuCategoryResponse(
                id=category.id,
                name=category.name,
                sort_order=category.sort_order,
                products=[
                    ProductResponse.from_entity(product)
                    for product in products
                    if product.category_id == category.id
                ],
            )
            for category in categories
        ],
    )


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, MenuNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc) or "Menu resource not found")
    if isinstance(exc, OrganizationAccessDenied):
        return HTTPException(status.HTTP_403_FORBIDDEN, "Location access denied")
    if isinstance(exc, InvalidModifierRecipe):
        return HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "INVALID_MODIFIER_RECIPE", "message": str(exc)},
        )
    if isinstance(exc, InvalidModifierSelection):
        return HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "INVALID_MODIFIER_SELECTION", "message": str(exc)},
        )
    if isinstance(exc, (MenuConflict, InvalidMenuOperation, IntegrityError)):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc) or "Menu conflict")
    if isinstance(exc, ValueError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    raise exc
