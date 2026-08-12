const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type User = {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  is_active: boolean;
  email_verified: boolean;
  created_at: string;
  updated_at: string;
};

export type RegisterInput = {
  email: string;
  password: string;
  first_name: string;
  last_name: string;
};

type Token = {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
};

export type Organization = {
  id: string;
  name: string;
  country_code: string;
  currency_code: string;
  status: "active" | "suspended" | "archived";
  created_by: string;
  created_at: string;
  updated_at: string;
};

export type Location = {
  id: string;
  organization_id: string;
  name: string;
  timezone: string;
  address: string | null;
  is_active: boolean;
  is_primary: boolean;
  created_at: string;
  updated_at: string;
};

export type CreateWorkspaceInput = {
  name: string;
  country_code: string;
  currency_code: string;
  first_location: {
    name: string;
    timezone: string;
    address?: string;
  };
};

export type CreatedWorkspace = {
  organization: Organization;
  location: Location;
  membership: { role: "OWNER" };
};

export type MembershipRole =
  | "OWNER"
  | "ADMIN"
  | "MANAGER"
  | "ACCOUNTANT"
  | "CASHIER"
  | "BARISTA";

export type OrganizationContext = {
  organization_id: string;
  user_id: string;
  membership_id: string;
  role: MembershipRole;
  permissions: string[];
  location_access: "ALL" | "SELECTED";
  location_ids: string[];
};

export type TeamMember = {
  employee_id: string | null;
  user_id: string | null;
  first_name: string;
  last_name: string;
  phone: string | null;
  position: string | null;
  email: string | null;
  role: MembershipRole | null;
  status: string;
  location_access: "ALL" | "SELECTED" | null;
  locations: string[];
};

export type Team = {
  members: TeamMember[];
  invitations: Invitation[];
  permissions: string[];
};

export type Invitation = {
  id: string;
  organization_id: string;
  employee_id: string | null;
  email: string;
  role: MembershipRole;
  status: "PENDING" | "ACCEPTED" | "EXPIRED" | "REVOKED";
  expires_at: string;
  invited_by: string;
  accepted_by: string | null;
  accepted_at: string | null;
  location_ids: string[];
  created_at: string;
};

export type PublicInvitation = {
  organization_name: string;
  email: string;
  role: MembershipRole;
  expires_at: string;
};

export type CreateInvitationInput = {
  email: string;
  role: Exclude<MembershipRole, "OWNER">;
  location_ids: string[];
};

export type InventoryUnitCode = "g" | "kg" | "ml" | "l" | "pcs";

export type MenuCategory = {
  id: string;
  organization_id: string;
  name: string;
  sort_order: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type ProductStatus = "DRAFT" | "ACTIVE" | "ARCHIVED";
export type ProductVariantStatus = "DRAFT" | "ACTIVE" | "ARCHIVED";

export type ProductVariant = {
  id: string;
  organization_id: string;
  product_id: string;
  name: string;
  sku: string | null;
  base_price_minor: string;
  location_price_minor: string | null;
  effective_price_minor: string;
  is_default: boolean;
  status: ProductVariantStatus;
  sort_order: number;
  created_at: string;
  updated_at: string;
  modifier_groups?: ModifierGroupMenu[];
};

export type ModifierSelectionType = "SINGLE" | "MULTIPLE";

export type ModifierOptionComponent = {
  id?: string;
  modifier_option_id?: string;
  inventory_item_id: string;
  quantity_delta: string;
  sort_order: number;
  item_name?: string;
  base_unit?: InventoryUnitCode;
};

export type ModifierOptionMenu = {
  id: string;
  name: string;
  base_price_delta_minor: string;
  location_price_delta_minor: string | null;
  effective_price_delta_minor: string;
  is_default: boolean;
  sort_order: number;
  is_available: boolean;
};

export type ModifierOption = ModifierOptionMenu & {
  organization_id: string;
  modifier_group_id: string;
  is_active: boolean;
  component_count?: number;
  components: ModifierOptionComponent[];
  created_at: string;
  updated_at: string;
};

export type ModifierGroupMenu = {
  id: string;
  name: string;
  selection_type: ModifierSelectionType;
  min_selections: number;
  max_selections: number;
  sort_order: number;
  is_active: boolean;
  options: ModifierOptionMenu[];
};

export type ModifierGroup = Omit<ModifierGroupMenu, "options"> & {
  organization_id: string;
  product_variant_id: string;
  is_active: boolean;
  options: ModifierOption[];
  created_at: string;
  updated_at: string;
};

export type CustomizationPreview = {
  variant_id: string;
  selected_option_ids: string[];
  base_price_minor: string;
  modifier_price_minor: string;
  final_price_minor: string;
  base_recipe_cost: string | null;
  modifier_cost_delta: string | null;
  final_cost: string | null;
  food_cost_percent: string | null;
  gross_profit: string | null;
  gross_margin_percent: string | null;
  status: RecipeCostStatus;
  missing_cost_items: string[];
  effective_components: Array<{
    inventory_item_id: string;
    name: string;
    quantity: string;
    base_unit: InventoryUnitCode;
    unit_cost: string | null;
    cost: string | null;
  }>;
};

export type MenuProduct = {
  id: string;
  organization_id: string;
  category_id: string;
  category_name?: string;
  name: string;
  description: string | null;
  image_url: string | null;
  status: ProductStatus;
  is_available: boolean | null;
  is_visible: boolean | null;
  variants: ProductVariant[];
  created_at: string;
  updated_at: string;
};

export type CreateProductInput = {
  category_id: string;
  name: string;
  description?: string | null;
  image_url?: string | null;
  default_variant?: {
    name?: string;
    sku?: string | null;
    base_price_minor?: string;
  };
};

export type RecipeComponent = {
  id: string;
  inventory_item_id: string;
  item_name: string;
  base_unit: InventoryUnitCode;
  quantity: string;
  sort_order: number;
};

export type Recipe = {
  id: string;
  variant_id: string;
  name: string;
  yield_quantity: string;
  is_active: boolean;
  components: RecipeComponent[];
};

export type RecipeCostStatus = "COMPLETE" | "INCOMPLETE";

export type RecipeCost = {
  variant_id: string;
  price_minor: string;
  currency_code?: string;
  recipe_cost: string | null;
  food_cost_percent: string | null;
  gross_profit: string | null;
  gross_margin_percent: string | null;
  status: RecipeCostStatus;
  missing_cost_items: string[];
  components: Array<{
    inventory_item_id?: string;
    name: string;
    quantity: string;
    base_unit?: InventoryUnitCode;
    unit?: InventoryUnitCode;
    unit_cost: string | null;
    cost: string | null;
  }>;
};

export type MenuCostSummary = {
  warehouse_id: string;
  variants: Array<{
    variant_id: string;
    price_minor: string;
    recipe_cost: string | null;
    status: RecipeCostStatus;
    missing_cost_items: string[];
  }>;
};

export type MenuReadModel = {
  location_id: string;
  categories: Array<{
    id: string;
    name: string;
    sort_order: number;
    products: MenuProduct[];
  }>;
};

export type PosRegister = {
  id: string;
  organization_id: string;
  location_id: string;
  name: string;
  is_active: boolean;
  created_by_user_id: string;
  created_at: string;
  updated_at: string;
};

export type PosWarehouseChoice = {
  id: string;
  location_id: string;
  name: string;
};

export type RegisterShiftStatus = "OPEN" | "CLOSED";

export type RegisterShift = {
  id: string;
  organization_id: string;
  location_id: string;
  register_id: string;
  warehouse_id: string;
  status: RegisterShiftStatus;
  opened_by_user_id: string;
  closed_by_user_id: string | null;
  opened_at: string;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type SalesOrderType = "DINE_IN" | "TAKEAWAY" | "DELIVERY";
export type SalesOrderStatus = "OPEN" | "PAID" | "CANCELLED";

export type SalesOrderModifier = {
  id: string;
  order_item_id: string;
  modifier_group_id: string;
  modifier_group_name: string;
  modifier_option_id: string;
  modifier_option_name: string;
  price_delta_minor: string;
  sort_order: number;
};

export type SalesOrderComponent = {
  id: string;
  order_item_id: string;
  inventory_item_id: string;
  inventory_item_name: string;
  base_unit: InventoryUnitCode;
  quantity_per_unit: string;
  created_at: string;
};

export type SalesOrderItem = {
  id: string;
  order_id: string;
  client_item_id: string;
  product_id: string;
  product_variant_id: string;
  product_name: string;
  variant_name: string;
  quantity: number;
  base_price_minor: string;
  modifier_price_minor: string;
  unit_price_minor: string;
  line_total_minor: string;
  note: string | null;
  created_at: string;
  updated_at: string;
  modifiers: SalesOrderModifier[];
  components: SalesOrderComponent[];
};

export type SalesOrder = {
  id: string;
  organization_id: string;
  location_id: string;
  shift_id: string;
  warehouse_id: string;
  number: string;
  client_order_id: string;
  order_type: SalesOrderType;
  status: SalesOrderStatus;
  currency_code: string;
  guest_count: number | null;
  table_label: string | null;
  note: string | null;
  subtotal_minor: string;
  total_minor: string;
  created_by_user_id: string;
  cancelled_by_user_id: string | null;
  cancelled_at: string | null;
  cancel_reason: string | null;
  created_at: string;
  updated_at: string;
  items: SalesOrderItem[];
};

export type PaymentMethod = "CASH" | "CARD" | "OTHER";

export type PaymentMethodChoice = {
  code: PaymentMethod;
  name: string;
};

export type PaymentLineInput = {
  method: PaymentMethod;
  amount_minor: string;
  cash_received_minor?: string;
  reference?: string;
};

export type PaymentLine = {
  id: string;
  payment_id: string;
  method: PaymentMethod;
  amount_minor: string;
  cash_received_minor: string | null;
  change_minor: string;
  reference: string | null;
  external_payment_attempt_id: string | null;
  provider_code: string | null;
  provider_transaction_id: string | null;
  sort_order: number;
  created_at: string;
};

export type Payment = {
  id: string;
  organization_id: string;
  location_id: string;
  order_id: string;
  shift_id: string;
  client_payment_id: string;
  currency_code: string;
  amount_minor: string;
  created_by_user_id: string;
  completed_at: string;
  created_at: string;
  updated_at: string;
  lines: PaymentLine[];
};

export type RefundReason =
  | "QUALITY_ISSUE"
  | "WRONG_ITEM"
  | "ORDER_ERROR"
  | "CUSTOMER_RETURN"
  | "DUPLICATE_PAYMENT"
  | "GOODWILL"
  | "OTHER";

export type RefundStatus = "PENDING" | "COMPLETED" | "FAILED";
export type RefundFiscalStatus = "NOT_CONFIGURED" | "PENDING" | "PROCESSING" | "RETRYING" | "SUCCESS" | "DEAD";

export type RefundRequestLine = {
  order_item_id: string;
  quantity: number;
  restock_quantity: number;
};

export type RefundPaymentRequestLine = {
  original_payment_line_id: string;
  amount_minor: string;
  external_refund_confirmed?: boolean;
  reference?: string | null;
};

export type RefundPreviewRequest = {
  payment_id: string;
  reason: RefundReason;
  note?: string | null;
  lines: RefundRequestLine[];
  payment_lines: RefundPaymentRequestLine[];
};

export type RefundPreview = {
  payment_id: string;
  order_id: string;
  currency_code: string;
  total_amount_minor: string;
  lines: Array<{
    order_item_id: string;
    product_name: string;
    variant_name: string;
    original_quantity: number;
    already_refunded_quantity: number;
    available_quantity: number;
    quantity: number;
    restock_quantity: number;
    unit_refund_minor: string;
    total_refund_minor: string;
  }>;
  payment_lines: Array<{
    original_payment_line_id: string;
    method: PaymentMethod;
    original_amount_minor: string;
    already_refunded_minor: string;
    available_amount_minor: string;
    amount_minor: string;
  }>;
};

export type Refund = {
  id: string;
  organization_id: string;
  location_id: string;
  order_id: string;
  payment_id: string;
  client_refund_id: string;
  status: RefundStatus;
  reason: RefundReason;
  note: string | null;
  currency_code: string;
  total_amount_minor: string;
  inventory_transaction_id: string | null;
  cogs_reversal_amount: string;
  cogs_quality_status: "COMPLETE" | "INCOMPLETE" | "ESTIMATED" | null;
  created_by_user_id: string;
  created_at: string;
  completed_by_user_id: string | null;
  completed_at: string | null;
  failure_code: string | null;
  fiscal_status: RefundFiscalStatus;
  fiscal_external_number: string | null;
  fiscal_external_url: string | null;
  lines: Array<{
    id: string;
    order_item_id: string;
    quantity: number;
    restock_quantity: number;
    unit_refund_minor: string;
    total_refund_minor: string;
  }>;
  payment_lines: Array<{
    id: string;
    original_payment_line_id: string;
    method: PaymentMethod;
    amount_minor: string;
    external_refund_confirmed: boolean;
    reference: string | null;
  }>;
};

export type FiscalTaxProfile = {
  id: string;
  organization_id: string;
  country_code: string;
  tax_regime_code: string;
  vat_registered: boolean;
  default_vat_rate: string | null;
  effective_from: string;
  effective_to: string | null;
  created_by: string;
  created_at: string;
};

export type FiscalVariantProfile = {
  id: string;
  organization_id: string;
  product_variant_id: string;
  fiscal_name: string;
  nkt_code: string | null;
  nkt_code_type: string | null;
  fiscal_unit_code: string;
  vat_rate_override: string | null;
  requires_marking: boolean;
  nkt_verified_at: string | null;
  nkt_external_product_id: string | null;
  updated_at: string;
};

export type FiscalReadiness = {
  ready: boolean;
  readiness_percent: number;
  tax_profile: "COMPLETE" | "MISSING";
  location: "COMPLETE" | "MISSING";
  unmapped_variants: Array<{ variant_id: string; name: string; reason: string }>;
};

export type NktProduct = {
  external_id: string;
  ntin: string;
  gtins: string[];
  name_ru: string;
  name_kk: string;
  category_code: string;
  unit_code: string | null;
  status: string;
  updated_at: string | null;
};

export type FiscalReceiptStatus =
  | "PENDING"
  | "PROCESSING"
  | "SUCCEEDED"
  | "RETRYING"
  | "UNKNOWN"
  | "DEAD";

export type FiscalReceipt = {
  id: string;
  organization_id: string;
  location_id: string;
  connection_id: string;
  source_type: "SALE" | "REFUND";
  source_id: string;
  provider_code: string;
  status: FiscalReceiptStatus;
  external_receipt_id: string | null;
  receipt_number: string | null;
  receipt_url: string | null;
  provider_request_id: string | null;
  provider_correlation_id: string;
  fiscalized_at: string | null;
  last_error_code: string | null;
  last_error_message: string | null;
  created_at: string;
  updated_at: string;
};

export type FiscalOperations = {
  provider_code: string | null;
  connected: boolean;
  receipts_today: number;
  successful_today: number;
  pending: number;
  failed: number;
  unknown: number;
  oldest_pending_seconds: number | null;
};

export type FiscalReceiptList = {
  items: FiscalReceipt[];
  total: number;
  limit: number;
  offset: number;
};

export type FiscalEnforcementMode = "DISABLED" | "TEST" | "LIVE_REQUIRED";

export type FiscalEnforcement = {
  location_id: string;
  mode: FiscalEnforcementMode;
};

export type FiscalGoLiveReadiness = {
  ready: boolean;
  checks: Record<string, boolean>;
};

export type FiscalRoute = {
  id: string;
  organization_id: string;
  location_id: string;
  register_id: string;
  provider_connection_id: string;
  source_mode: "EXTERNAL_KKM" | "PAYMENT_TERMINAL_KKM";
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type TerminalBinding = {
  id: string;
  organization_id: string;
  connection_id: string;
  location_id: string;
  register_id: string;
  provider_code: string;
  external_terminal_id: string | null;
  transport_config: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type ExternalPaymentAttemptStatus =
  | "CREATED"
  | "TERMINAL_PENDING"
  | "APPROVED"
  | "DECLINED"
  | "CANCELLED"
  | "UNKNOWN";

export type ExternalPaymentAttempt = {
  id: string;
  organization_id: string;
  location_id: string;
  order_id: string;
  register_id: string;
  pos_device_id: string | null;
  connection_id: string;
  client_attempt_id: string;
  provider_code: string;
  method: "CARD" | "QR";
  amount_minor: string;
  currency_code: string;
  status: ExternalPaymentAttemptStatus;
  provider_operation_id: string | null;
  provider_reference: string | null;
  created_by_user_id: string;
  created_at: string;
  approved_at: string | null;
  failed_at: string | null;
  failure_code: string | null;
  payment_id: string | null;
};

export type WarehouseResponse = {
  id: string;
  organization_id: string;
  location_id: string;
  name: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type InventoryItemResponse = {
  id: string;
  organization_id: string;
  name: string;
  sku: string | null;
  base_unit: InventoryUnitCode;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type StockRow = {
  warehouse_id: string;
  inventory_item_id: string;
  item_name: string;
  sku: string | null;
  quantity: string;
  base_unit: InventoryUnitCode;
  average_unit_cost: string | null;
  inventory_value: string | null;
  updated_at: string | null;
};

export type InventoryValuation = {
  currency_code: string;
  total_inventory_value: string;
  items: StockRow[];
};

export type MovementRow = {
  transaction_id: string;
  type: string;
  status: "DRAFT" | "POSTED" | "REVERSED";
  quantity_delta: string;
  unit_cost_amount: string | null;
  total_cost_amount: string | null;
  quantity_after: string | null;
  average_unit_cost_after: string | null;
  reference_type: string | null;
  reference_id: string | null;
  note: string | null;
  posted_at: string | null;
  created_at: string;
};

export type TransactionDetail = {
  id: string;
  organization_id: string;
  location_id: string;
  warehouse_id: string;
  type: string;
  status: "DRAFT" | "POSTED" | "REVERSED";
  reference_type: string | null;
  reference_id: string | null;
  idempotency_key: string | null;
  note: string | null;
  created_by: string;
  created_at: string;
  posted_at: string | null;
  reversal_of_id: string | null;
  lines: Array<{
    id: string;
    transaction_id: string;
    inventory_item_id: string;
    quantity_delta: string;
    unit_cost_amount: string | null;
    total_cost_amount: string | null;
    quantity_after: string | null;
    average_unit_cost_after: string | null;
    created_at: string;
  }>;
};

export type CreateAdjustmentInput = {
  warehouse_id: string;
  reason: string;
  lines: Array<{
    inventory_item_id: string;
    quantity: string;
    unit_code: InventoryUnitCode;
    unit_cost_amount?: string;
  }>;
};

export type InventoryDocumentStatus = "DRAFT" | "POSTED" | "REVERSED";

export type WriteOffReason = {
  id: string;
  organization_id: string;
  name: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type InventoryDocumentLine = {
  id: string;
  inventory_item_id: string;
  item_name?: string;
  quantity: string;
  unit_code: InventoryUnitCode;
  base_quantity: string;
  note?: string | null;
};

export type InventoryWriteOff = {
  id: string;
  organization_id: string;
  location_id: string;
  warehouse_id: string;
  number: string;
  reason_id: string;
  reason_name?: string;
  status: InventoryDocumentStatus;
  occurred_at: string;
  note: string | null;
  inventory_transaction_id: string | null;
  total_cost_amount: string | null;
  created_at: string;
  updated_at: string;
  posted_at: string | null;
  reversed_at: string | null;
  lines: InventoryDocumentLine[];
};

export type InventoryCountStatus = "COUNTING" | "POSTED" | "CANCELLED";
export type InventoryCountType = "FULL" | "PARTIAL";

export type InventoryCountLine = {
  id: string;
  inventory_item_id: string;
  item_name?: string;
  base_unit?: InventoryUnitCode;
  unit_code?: InventoryUnitCode;
  expected_quantity: string;
  counted_quantity: string | null;
  current_quantity_before_post: string | null;
  difference_quantity: string | null;
  difference_cost_amount: string | null;
  unit_cost_amount: string | null;
};

export type InventoryCount = {
  id: string;
  organization_id: string;
  location_id: string;
  warehouse_id: string;
  number: string;
  type: InventoryCountType;
  status: InventoryCountStatus;
  snapshot_at: string;
  note: string | null;
  inventory_transaction_id: string | null;
  created_at: string;
  updated_at: string;
  posted_at: string | null;
  cancelled_at: string | null;
  lines: InventoryCountLine[];
};

export type InventoryTransfer = {
  id: string;
  organization_id: string;
  number: string;
  source_location_id: string;
  source_warehouse_id: string;
  destination_location_id: string;
  destination_warehouse_id: string;
  status: InventoryDocumentStatus;
  occurred_at: string;
  note: string | null;
  out_transaction_id: string | null;
  in_transaction_id: string | null;
  created_at: string;
  updated_at: string;
  posted_at: string | null;
  reversed_at: string | null;
  lines: InventoryDocumentLine[];
};

export type InventoryMovement = {
  transaction_id: string;
  line_id?: string;
  warehouse_id: string;
  inventory_item_id: string;
  item_name: string;
  unit_code: InventoryUnitCode;
  type: string;
  quantity_delta: string;
  unit_cost_amount: string | null;
  total_cost_amount: string | null;
  reference_type: string | null;
  reference_id: string | null;
  posted_at: string;
};

export type Supplier = {
  id: string;
  organization_id: string;
  name: string;
  contact_name: string | null;
  phone: string | null;
  email: string | null;
  tax_id: string | null;
  address: string | null;
  note: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type SupplierInput = {
  name: string;
  contact_name?: string | null;
  phone?: string | null;
  email?: string | null;
  tax_id?: string | null;
  address?: string | null;
  note?: string | null;
};

export type PurchaseOrderStatus =
  | "DRAFT"
  | "ORDERED"
  | "PARTIALLY_RECEIVED"
  | "RECEIVED"
  | "CANCELLED";

export type PurchaseOrderLine = {
  id: string;
  purchase_order_id: string;
  inventory_item_id: string;
  ordered_quantity: string;
  base_quantity: string;
  purchase_unit: string;
  unit_multiplier: string;
  unit_price: string;
  line_total_minor: string | number;
  received_base_quantity?: string;
  remaining_base_quantity?: string;
  created_at: string;
  updated_at: string;
};

export type PurchaseOrder = {
  id: string;
  organization_id: string;
  location_id: string;
  warehouse_id: string;
  supplier_id: string;
  supplier_name?: string;
  location_name?: string;
  warehouse_name?: string;
  number: string;
  status: PurchaseOrderStatus;
  currency_code: string;
  ordered_at: string | null;
  expected_at: string | null;
  note: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  total_minor?: string | number;
  lines: PurchaseOrderLine[];
};

export type PurchaseOrderLineInput = {
  inventory_item_id: string;
  quantity: string;
  purchase_unit: string;
  unit_multiplier?: string;
  unit_price: string;
};

export type PurchaseOrderInput = {
  supplier_id: string;
  location_id: string;
  warehouse_id: string;
  expected_at?: string | null;
  note?: string | null;
  lines: PurchaseOrderLineInput[];
};

export type GoodsReceiptStatus = "DRAFT" | "POSTED" | "REVERSED";

export type GoodsReceiptLine = {
  id: string;
  goods_receipt_id: string;
  purchase_order_line_id: string | null;
  inventory_item_id: string;
  received_quantity: string;
  base_quantity: string;
  purchase_unit: string;
  unit_multiplier: string;
  unit_price: string;
  line_total_minor: string | number;
  returned_base_quantity?: string;
  returnable_base_quantity?: string;
  created_at: string;
};

export type GoodsReceipt = {
  id: string;
  organization_id: string;
  location_id: string;
  warehouse_id: string;
  purchase_order_id: string | null;
  supplier_id: string;
  supplier_name?: string;
  location_name?: string;
  warehouse_name?: string;
  purchase_order_number?: string | null;
  number: string;
  status: GoodsReceiptStatus;
  document_number: string | null;
  received_at: string;
  note: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  posted_by: string | null;
  posted_at: string | null;
  reversed_by: string | null;
  reversed_at: string | null;
  inventory_transaction_id: string | null;
  total_minor?: string | number;
  lines: GoodsReceiptLine[];
};

export type GoodsReceiptLineInput = {
  purchase_order_line_id?: string | null;
  inventory_item_id: string;
  quantity: string;
  purchase_unit: string;
  unit_multiplier?: string;
  unit_price: string;
};

export type GoodsReceiptInput = {
  purchase_order_id?: string | null;
  supplier_id: string;
  location_id: string;
  warehouse_id: string;
  document_number?: string | null;
  received_at: string;
  note?: string | null;
  lines: GoodsReceiptLineInput[];
};

export type SupplierReturnStatus = "DRAFT" | "POSTED" | "REVERSED";

export type SupplierReturnLine = {
  id: string;
  supplier_return_id: string;
  goods_receipt_line_id: string | null;
  inventory_item_id: string;
  item_name?: string;
  return_quantity: string;
  base_quantity: string;
  purchase_unit: string;
  unit_multiplier: string;
  unit_price: string;
  line_total_minor: string;
  cumulative_returned_base_quantity: string;
  created_at: string;
};

export type SupplierReturn = {
  id: string;
  organization_id: string;
  location_id: string;
  warehouse_id: string;
  supplier_id: string;
  supplier_name?: string;
  goods_receipt_id: string | null;
  goods_receipt_number?: string | null;
  number: string;
  status: SupplierReturnStatus;
  document_number: string | null;
  returned_at: string;
  note: string | null;
  inventory_transaction_id: string | null;
  total_minor?: string;
  created_at: string;
  updated_at: string;
  posted_at: string | null;
  reversed_at: string | null;
  lines: SupplierReturnLine[];
};

export type FinancePnl = {
  currency_code: string;
  revenue: string;
  cogs: string;
  gross_profit: string;
  inventory_losses: string;
  inventory_gains: string;
  operating_expenses: string;
  other_income: string;
  other_expenses: string;
  operating_profit: string;
  gross_margin_percent: string | null;
  data_quality: { cogs_complete: boolean; incomplete_cogs_sales: number };
};

export type FinancePnlBreakdown = {
  currency_code: string;
  operating_expenses: Array<{ category_id: string | null; name: string; amount: string }>;
};

export type CashFlowSection = {
  inflows_minor: string;
  outflows_minor: string;
  net_minor: string;
};

export type FinanceCashFlow = {
  currency_code: string;
  opening_cash_minor: string;
  operating: CashFlowSection;
  investing: CashFlowSection;
  financing: CashFlowSection;
  net_cash_movement_minor: string;
  closing_cash_minor: string;
};

export type DashboardPeriod =
  | "TODAY"
  | "YESTERDAY"
  | "LAST_7_DAYS"
  | "THIS_MONTH"
  | "CUSTOM";

export type DashboardDirection = "UP" | "DOWN" | "FLAT";

export type DashboardMetric<T extends string | number> = {
  current: T;
  previous: T;
  absolute_change: T;
  percent_change: string | null;
  direction: DashboardDirection;
};

export type DashboardAlert = {
  code: string;
  severity: "INFO" | "WARNING" | "CRITICAL";
  title: string;
  message: string;
  location_id: string | null;
  entity_type: string | null;
  entity_id: string | null;
  action_href: string;
};

export type DashboardOverview = {
  scope: {
    organization_id: string;
    location_id: string | null;
    location_name: string;
    timezone: string;
    period: DashboardPeriod;
    current: { from: string; to: string };
    previous: { from: string; to: string };
  };
  sales: {
    revenue: DashboardMetric<string>;
    gross_sales_minor: string;
    refund_amount_minor: string;
    net_sales_minor: string;
    paid_orders: DashboardMetric<number>;
    average_check: DashboardMetric<string>;
    open_orders: number;
    open_shifts: number;
  };
  finance: null | {
    currency_code: string;
    cogs: string;
    gross_profit: string;
    gross_margin_percent: string | null;
    operating_expenses: string;
    inventory_losses: string;
    inventory_gains: string;
    operating_profit: string;
    operating_profit_comparison: DashboardMetric<string>;
    net_cash_movement_minor: string;
    incomplete_cogs_sales: number;
    data_as_of: string | null;
  };
  inventory: {
    total_value: string;
    negative_stock_count: number;
    active_count_count: number;
    negative_items: Array<{
      item_id: string;
      location_id: string;
      name: string;
      quantity: string;
      unit_code: string;
    }>;
  };
  payment_mix: Array<{
    method: string;
    amount: string;
    share_percent: string;
  }>;
  trend: Array<{
    bucket_start: string;
    revenue: string;
    gross_sales_minor: string;
    refund_amount_minor: string;
    net_sales_minor: string;
    orders: number;
  }>;
  locations: Array<{
    location_id: string;
    location_name: string;
    revenue: string;
    gross_sales_minor: string;
    refund_amount_minor: string;
    net_sales_minor: string;
    paid_orders: number;
    average_check: string;
    operating_profit: string | null;
  }>;
  alerts: DashboardAlert[];
};

export type AnalyticsGroupBy = "PRODUCT" | "VARIANT";
export type AnalyticsProductSort = "REVENUE" | "QUANTITY" | "GROSS_PROFIT";
export type AnalyticsHourMetric = "REVENUE" | "ORDERS" | "ITEMS";
export type AnalyticsMenuClass = "HERO" | "WORKHORSE" | "PUZZLE" | "LOW_PERFORMER";
export type AnalyticsRangeFilters = { dateFrom: string; dateTo: string; locationId?: string };

export type AnalyticsOverview = {
  organization_id: string;
  location_id: string | null;
  date_from: string;
  date_to: string;
  currency_code: string;
  revenue: string;
  gross_revenue: string;
  refund_amount: string;
  net_revenue: string;
  paid_orders: number;
  items_sold: number;
  average_check: string;
  cogs: string | null;
  gross_profit: string | null;
  gross_margin_percent: string | null;
  inventory_losses: string | null;
  incomplete_cogs_orders: number | null;
  data_as_of: string | null;
};

export type AnalyticsProductRow = {
  product_id: string;
  product_variant_id: string | null;
  name: string;
  variant_name: string | null;
  quantity_sold: number;
  revenue: string;
  gross_revenue: string;
  refund_amount: string;
  net_revenue: string;
  refunded_quantity: number;
  refund_orders: number;
  orders: number;
  cogs: string | null;
  gross_profit: string | null;
  gross_margin_percent: string | null;
  incomplete_cogs_orders: number | null;
};

export type AnalyticsProducts = {
  group_by: AnalyticsGroupBy;
  rows: AnalyticsProductRow[];
  data_as_of: string | null;
};

export type AnalyticsAbc = {
  thresholds: { a_max_cumulative_share: string; b_max_cumulative_share: string };
  rows: Array<{
    product_id: string;
    name: string;
    revenue: string;
    revenue_share_percent: string;
    cumulative_share_percent: string;
    abc_class: "A" | "B" | "C";
  }>;
  data_as_of: string | null;
};

export type AnalyticsMenuEngineering = {
  thresholds: {
    popularity_factor: string;
    expected_popularity_share_percent: string;
    high_popularity_share_percent: string;
    average_contribution_margin_per_item: string;
  };
  rows: Array<{
    product_id: string;
    name: string;
    quantity_sold: number;
    revenue: string;
    orders: number;
    popularity_share_percent: string;
    contribution_margin_per_item: string;
    gross_margin_percent: string | null;
    classification: AnalyticsMenuClass;
  }>;
  data_as_of: string | null;
};

export type AnalyticsHours = {
  metric: AnalyticsHourMetric;
  rows: Array<{ day_of_week: number; local_hour: number; value: string }>;
  data_as_of: string | null;
};

export type AnalyticsInventoryConsumption = {
  rows: Array<{
    inventory_item_id: string;
    name: string;
    base_unit: string;
    sale_quantity: string;
    sale_cost_amount: string | null;
    writeoff_quantity: string;
    writeoff_cost_amount: string | null;
    adjustment_quantity: string;
    waste_rate_percent: string | null;
  }>;
  data_as_of: string | null;
};

export type AnalyticsLocations = {
  rows: Array<{
    location_id: string;
    location_name: string;
    revenue: string;
    gross_revenue: string;
    refund_amount: string;
    net_revenue: string;
    paid_orders: number;
    items_sold: number;
    average_check: string;
    cogs: string | null;
    gross_profit: string | null;
    gross_margin_percent: string | null;
    operating_expenses: string | null;
    operating_profit: string | null;
    revenue_rank: number;
    orders_rank: number;
    average_check_rank: number;
    gross_margin_rank: number | null;
    operating_profit_rank: number | null;
  }>;
  data_as_of: string | null;
};

export type IntegrationCapability =
  | "PAYMENT"
  | "FISCAL"
  | "DELIVERY"
  | "NOTIFICATION";
export type IntegrationAuthType = "NONE" | "API_KEY" | "OAUTH2";
export type IntegrationConnectionStatus = "PENDING" | "ACTIVE" | "DEGRADED" | "REVOKED";
export type IntegrationJobStatus = "PENDING" | "PROCESSING" | "RETRYING" | "SUCCESS" | "DEAD";

export type IntegrationProvider = {
  code: string;
  name: string;
  capabilities: IntegrationCapability[];
  auth_type: IntegrationAuthType;
  supports_webhooks: boolean;
  supports_health_check: boolean;
  location_scoped: boolean;
};

export type IntegrationLocationBinding = {
  id: string;
  location_id: string;
  capability: IntegrationCapability;
  external_location_id: string | null;
  settings: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type IntegrationConnection = {
  id: string;
  provider_code: string;
  display_name: string;
  status: IntegrationConnectionStatus;
  auth_type: IntegrationAuthType;
  config: Record<string, unknown>;
  has_credentials: boolean;
  external_account_id: string | null;
  connected_at: string | null;
  last_health_check_at: string | null;
  last_success_at: string | null;
  last_error_code: string | null;
  last_error_message: string | null;
  created_at: string;
  updated_at: string;
  can_manage: boolean;
  bindings: IntegrationLocationBinding[];
};

export type IntegrationJobAttempt = {
  attempt_number: number;
  started_at: string;
  finished_at: string;
  outcome: "SUCCESS" | "TEMPORARY_FAILURE" | "PERMANENT_FAILURE";
  http_status: number | null;
  provider_request_id: string | null;
  duration_ms: number | null;
  error_code: string | null;
  error_message: string | null;
};

export type IntegrationJob = {
  id: string;
  connection_id: string;
  location_id: string | null;
  capability: IntegrationCapability;
  job_type: string;
  source_type: string;
  source_id: string;
  idempotency_key: string;
  status: IntegrationJobStatus;
  available_at: string;
  attempts: number;
  external_id: string | null;
  completed_at: string | null;
  dead_lettered_at: string | null;
  last_error_code: string | null;
  last_error_message: string | null;
  created_at: string;
  updated_at: string;
  attempt_history: IntegrationJobAttempt[];
};

export type IntegrationJobList = {
  items: IntegrationJob[];
  total: number;
  limit: number;
  offset: number;
};

export type IntegrationConnectionInput = {
  provider_code: string;
  display_name: string;
  config?: Record<string, unknown>;
  credentials?: Record<string, unknown>;
};

export type ExpenseStatus = "DRAFT" | "POSTED" | "REVERSED";

export type ExpenseCategory = {
  id: string;
  organization_id: string;
  name: string;
  sort_order: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type CashAccountType = "CASH" | "CARD_CLEARING" | "BANK" | "OTHER";

export type CashAccount = {
  id: string;
  organization_id: string;
  location_id: string | null;
  name: string;
  type: CashAccountType;
  currency_code: string;
  system_key: string | null;
  opening_balance_minor: string;
  balance_minor: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type Expense = {
  id: string;
  organization_id: string;
  location_id: string | null;
  number: string;
  category_id: string;
  status: ExpenseStatus;
  amount_minor: string;
  currency_code: string;
  cash_account_id: string | null;
  vendor: string | null;
  occurred_at: string;
  description: string | null;
  created_by: string;
  posted_by: string | null;
  posted_at: string | null;
  reversed_by: string | null;
  reversed_at: string | null;
  finance_entry_id: string | null;
  cash_entry_id: string | null;
  created_at: string;
  updated_at: string;
};

export type ExpenseInput = {
  location_id?: string | null;
  category_id: string;
  amount_minor: string;
  cash_account_id?: string | null;
  vendor?: string | null;
  occurred_at: string;
  description?: string | null;
};

export type CashMovementType =
  | "SUPPLIER_PAYMENT"
  | "OWNER_CONTRIBUTION"
  | "OWNER_WITHDRAWAL"
  | "OTHER_INFLOW"
  | "OTHER_OUTFLOW"
  | "TRANSFER";

export type CashFlowActivity = "OPERATING" | "INVESTING" | "FINANCING";

export type CashMovement = {
  id: string;
  organization_id: string;
  location_id: string | null;
  type: CashMovementType;
  amount_minor: string;
  currency_code: string;
  from_account_id: string | null;
  to_account_id: string | null;
  cash_flow_activity: CashFlowActivity;
  occurred_at: string;
  description: string | null;
  created_by: string;
  reversed_by: string | null;
  reversed_at: string | null;
  out_entry_id: string | null;
  in_entry_id: string | null;
  created_at: string;
};

export type CashMovementInput = {
  location_id?: string | null;
  type: CashMovementType;
  amount_minor: string;
  from_account_id?: string | null;
  to_account_id?: string | null;
  cash_flow_activity: CashFlowActivity;
  occurred_at: string;
  description?: string | null;
};

export type OnboardingStatus = "NOT_STARTED" | "IN_PROGRESS" | "READY_FOR_POS" | "COMPLETED";
export type OnboardingStepStatus = "COMPLETE" | "NEEDS_ATTENTION" | "OPTIONAL" | "MISSING";
export type OnboardingStep = {
  status: OnboardingStepStatus;
  count: number;
  details: string[];
};
export type OnboardingStatusResponse = {
  status: OnboardingStatus;
  current_step: string | null;
  steps: Record<string, OnboardingStep>;
  pos_ready: boolean;
  ai_available: boolean;
  started_at: string | null;
  completed_at: string | null;
  dismissed_at: string | null;
};

export type OnboardingImportSourceType =
  | "BEANLY_TEMPLATE"
  | "BEANLY_SPREADSHEET"
  | "GENERIC_SPREADSHEET"
  | "POSTER_EXPORT"
  | "AI_EXTRACTION";
export type OnboardingImportStatus =
  | "UPLOADED"
  | "PARSING"
  | "NEEDS_REVIEW"
  | "READY"
  | "APPLYING"
  | "APPLIED"
  | "FAILED"
  | "CANCELLED";
export type OnboardingImportEntityType =
  | "CATEGORY"
  | "INVENTORY_ITEM"
  | "PRODUCT"
  | "VARIANT"
  | "RECIPE"
  | "MODIFIER_GROUP"
  | "MODIFIER_OPTION"
  | "LOCATION_PRICE"
  | "OPENING_BALANCE";
export type OnboardingImportResolution = "CREATE" | "MATCH_EXISTING" | "SKIP";
export type OnboardingImportEntity = {
  id: string;
  entity_type: OnboardingImportEntityType;
  source_key: string;
  payload: Record<string, unknown>;
  resolution: OnboardingImportResolution;
  target_id: string | null;
  error_codes: string[];
  warning_codes: string[];
  sort_order: number;
};
export type OnboardingImportRun = {
  id: string;
  organization_id: string;
  location_id: string;
  client_import_id: string;
  source_type: OnboardingImportSourceType;
  source_name: string;
  source_version: number | null;
  file_name: string | null;
  file_hash: string | null;
  status: OnboardingImportStatus;
  entity_count: number;
  error_count: number;
  warning_count: number;
  payload_hash: string;
  mapping: Record<string, string>;
  duplicate_file_run_id: string | null;
  duplicate_warning: string | null;
  created_by: string;
  created_at: string;
  applied_at: string | null;
  failed_at: string | null;
  entities: OnboardingImportEntity[];
};
export type OnboardingImportRunSummary = Omit<OnboardingImportRun, "entities">;
export type OnboardingTemplateOptions = {
  sizes: string[];
  alternative_milks: string[];
  extras: string[];
  packaging: boolean;
  include_draft_recipes: boolean;
};
export type OnboardingCapabilities = {
  ai: { available: boolean; reason: string | null };
  poster: { available: boolean; reason: string | null; real_fixture_verified: boolean; extensions: string[] };
  spreadsheet: { csv: boolean; xlsx: boolean; max_bytes: number };
};
export type OnboardingTemplateSummary = {
  code: string;
  version: number;
  name: string;
  description: string;
  category_count: number;
  product_count: number;
  has_draft_recipes: boolean;
};
export type OnboardingTemplateList = {
  items: OnboardingTemplateSummary[];
  spreadsheet_download_url: string;
};
export type OnboardingImportList = {
  items: OnboardingImportRunSummary[];
  total: number;
  limit: number;
  offset: number;
};
export type OnboardingImportValidation = {
  run: OnboardingImportRun;
  valid: boolean;
  error_count: number;
  warning_count: number;
};
export type OnboardingActivationResult = {
  items: Array<{ product_id: string; ready: boolean; reasons: string[] }>;
  activated_count: number;
};
export type OnboardingUploadSourceType =
  | "AUTO"
  | "BEANLY_SPREADSHEET"
  | "GENERIC_SPREADSHEET"
  | "POSTER";
export type OnboardingImportInspect = {
  file_hash: string;
  source_type: OnboardingImportSourceType;
  sheets: Array<{ name: string; columns: string[] }>;
  mapping_required: boolean;
};
export type OnboardingBootstrapResponse = {
  location_id: string;
  warehouse_id: string;
  register_id: string;
  created: { warehouse: boolean; register: boolean };
  onboarding: OnboardingStatusResponse;
};

type ApiErrorDetail = { code?: string; message?: string; msg?: string };
type ApiErrorBody = {
  detail?: string | ApiErrorDetail | Array<{ msg?: string }>;
  code?: string;
  message?: string;
  changed_items?: unknown;
};

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const isFormData = typeof FormData !== "undefined" && init.body instanceof FormData;
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      ...(init.body && !isFormData ? { "content-type": "application/json" } : {}),
      ...init.headers,
    },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as ApiErrorBody;
    const detail = Array.isArray(body.detail)
      ? body.detail[0]?.msg
      : typeof body.detail === "object"
        ? body.detail.message ?? body.detail.msg
        : body.detail;
    const code = body.code ?? (!Array.isArray(body.detail) && typeof body.detail === "object"
      ? body.detail.code
      : undefined);
    throw new ApiError(
      detail ?? body.message ?? "Something went wrong. Please try again.",
      response.status,
      code,
      body.detail ?? body,
    );
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

async function requestBlob(path: string, init: RequestInit = {}) {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as ApiErrorBody;
    const detail = typeof body.detail === "string" ? body.detail : body.message;
    throw new ApiError(detail ?? "Download could not be completed.", response.status, body.code, body);
  }
  return response.blob();
}

export const api = {
  register: (input: RegisterInput) =>
    request<User>("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  login: (email: string, password: string) =>
    request<Token>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  refresh: () => request<Token>("/api/v1/auth/refresh", { method: "POST" }),
  logout: () => request<void>("/api/v1/auth/logout", { method: "POST" }),
  me: (accessToken: string) =>
    request<User>("/api/v1/auth/me", {
      headers: { authorization: `Bearer ${accessToken}` },
    }),
  listOrganizations: (accessToken: string) =>
    request<Organization[]>("/api/v1/organizations", {
      headers: authorization(accessToken),
    }),
  createWorkspace: (input: CreateWorkspaceInput, accessToken: string) =>
    request<CreatedWorkspace>("/api/v1/organizations", {
      method: "POST",
      body: JSON.stringify(input),
      headers: authorization(accessToken),
    }),
  listLocations: (organizationId: string, accessToken: string) =>
    request<Location[]>(`/api/v1/organizations/${organizationId}/locations`, {
      headers: {
        ...authorization(accessToken),
        "X-Organization-ID": organizationId,
      },
    }),
  getOrganizationContext: (organizationId: string, accessToken: string) =>
    request<OrganizationContext>("/api/v1/organizations/context", {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  getTeam: (organizationId: string, accessToken: string) =>
    request<Team>("/api/v1/team", {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  listInvitations: (organizationId: string, accessToken: string) =>
    request<Invitation[]>("/api/v1/team/invitations", {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  createInvitation: (
    input: CreateInvitationInput,
    organizationId: string,
    accessToken: string,
  ) =>
    request<Invitation>("/api/v1/team/invitations", {
      method: "POST",
      body: JSON.stringify(input),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  revokeInvitation: (
    invitationId: string,
    organizationId: string,
    accessToken: string,
  ) =>
    request<void>(`/api/v1/team/invitations/${invitationId}/revoke`, {
      method: "POST",
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  inspectInvitation: (token: string) =>
    request<PublicInvitation>(`/api/v1/invitations/${token}`),
  acceptInvitation: (token: string, accessToken: string) =>
    request<void>(`/api/v1/invitations/${token}/accept`, {
      method: "POST",
      headers: authorization(accessToken),
    }),
  listInventoryWarehouses: (organizationId: string, accessToken: string) =>
    request<WarehouseResponse[]>("/api/v1/inventory/warehouses", {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  listInventoryItems: (organizationId: string, accessToken: string) =>
    request<InventoryItemResponse[]>("/api/v1/inventory/items", {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  listStock: (
    organizationId: string,
    accessToken: string,
    filters: { warehouseId?: string; locationId?: string; itemId?: string },
  ) =>
    request<StockRow[]>(
      `/api/v1/inventory/stock?${inventoryFilters(filters)}`,
      { headers: tenantAuthorization(organizationId, accessToken) },
    ),
  getInventoryValuation: (
    organizationId: string,
    accessToken: string,
    filters: { warehouseId?: string; locationId?: string },
  ) =>
    request<InventoryValuation>(
      `/api/v1/inventory/valuation?${inventoryFilters(filters)}`,
      { headers: tenantAuthorization(organizationId, accessToken) },
    ),
  getItemStock: (
    itemId: string,
    warehouseId: string,
    organizationId: string,
    accessToken: string,
  ) =>
    request<StockRow>(
      `/api/v1/inventory/items/${itemId}/stock?${new URLSearchParams({ warehouse_id: warehouseId })}`,
      { headers: tenantAuthorization(organizationId, accessToken) },
    ),
  listItemMovements: (
    itemId: string,
    warehouseId: string,
    organizationId: string,
    accessToken: string,
  ) =>
    request<MovementRow[]>(
      `/api/v1/inventory/items/${itemId}/movements?${new URLSearchParams({ warehouse_id: warehouseId })}`,
      { headers: tenantAuthorization(organizationId, accessToken) },
    ),
  createInventoryAdjustment: (
    input: CreateAdjustmentInput,
    organizationId: string,
    accessToken: string,
    idempotencyKey?: string,
  ) =>
    request<TransactionDetail>("/api/v1/inventory/adjustments", {
      method: "POST",
      body: JSON.stringify(input),
      headers: {
        ...tenantAuthorization(organizationId, accessToken),
        ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}),
      },
    }),
  createOpeningBalance: (
    input: {
      warehouse_id: string;
      items: CreateAdjustmentInput["lines"];
    },
    organizationId: string,
    accessToken: string,
    idempotencyKey?: string,
  ) =>
    request<TransactionDetail>("/api/v1/inventory/opening-balances", {
      method: "POST",
      body: JSON.stringify(input),
      headers: {
        ...tenantAuthorization(organizationId, accessToken),
        ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}),
      },
    }),
  listInventoryMovements: (
    organizationId: string,
    accessToken: string,
    filters: {
      warehouseId?: string;
      locationId?: string;
      inventoryItemId?: string;
      type?: string;
      dateFrom?: string;
      dateTo?: string;
      referenceType?: string;
    } = {},
  ) => request<InventoryMovement[]>(`/api/v1/inventory/movements?${operationFilters(filters)}`, {
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  listWriteOffReasons: (organizationId: string, accessToken: string, includeInactive = false) =>
    request<WriteOffReason[]>(`/api/v1/inventory/write-off-reasons?include_inactive=${includeInactive}`, {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  createWriteOffReason: (name: string, organizationId: string, accessToken: string) =>
    request<WriteOffReason>("/api/v1/inventory/write-off-reasons", {
      method: "POST",
      body: JSON.stringify({ name }),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  listWriteOffs: (organizationId: string, accessToken: string, filters: { warehouseId?: string; locationId?: string; status?: string } = {}) =>
    request<InventoryWriteOff[]>(`/api/v1/inventory/write-offs?${operationFilters(filters)}`, {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  getWriteOff: (id: string, organizationId: string, accessToken: string) =>
    request<InventoryWriteOff>(`/api/v1/inventory/write-offs/${id}`, {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  createWriteOff: (
    input: { warehouse_id: string; reason_id: string; occurred_at: string; note?: string | null; lines: Array<{ inventory_item_id: string; quantity: string; unit: InventoryUnitCode }> },
    organizationId: string,
    accessToken: string,
  ) => request<InventoryWriteOff>("/api/v1/inventory/write-offs", {
    method: "POST", body: JSON.stringify(input), headers: tenantAuthorization(organizationId, accessToken),
  }),
  postWriteOff: (id: string, organizationId: string, accessToken: string) =>
    request<InventoryWriteOff>(`/api/v1/inventory/write-offs/${id}/post`, { method: "POST", headers: tenantAuthorization(organizationId, accessToken) }),
  reverseWriteOff: (id: string, organizationId: string, accessToken: string) =>
    request<InventoryWriteOff>(`/api/v1/inventory/write-offs/${id}/reverse`, { method: "POST", headers: tenantAuthorization(organizationId, accessToken) }),
  listInventoryCounts: (organizationId: string, accessToken: string, filters: { warehouseId?: string; locationId?: string; status?: string } = {}) =>
    request<InventoryCount[]>(`/api/v1/inventory/counts?${operationFilters(filters)}`, { headers: tenantAuthorization(organizationId, accessToken) }),
  getInventoryCount: (id: string, organizationId: string, accessToken: string) =>
    request<InventoryCount>(`/api/v1/inventory/counts/${id}`, { headers: tenantAuthorization(organizationId, accessToken) }),
  createInventoryCount: (
    input: { warehouse_id: string; type: InventoryCountType; inventory_item_ids?: string[]; note?: string | null },
    organizationId: string,
    accessToken: string,
  ) => request<InventoryCount>("/api/v1/inventory/counts", { method: "POST", body: JSON.stringify(input), headers: tenantAuthorization(organizationId, accessToken) }),
  updateInventoryCountLines: (
    id: string,
    lines: Array<{ inventory_item_id: string; counted_quantity: string; unit: InventoryUnitCode; unit_cost_amount?: string }>,
    organizationId: string,
    accessToken: string,
  ) => request<InventoryCount>(`/api/v1/inventory/counts/${id}/lines`, { method: "PUT", body: JSON.stringify({ lines }), headers: tenantAuthorization(organizationId, accessToken) }),
  postInventoryCount: (id: string, confirmStockChanges: boolean, organizationId: string, accessToken: string) =>
    request<InventoryCount>(`/api/v1/inventory/counts/${id}/post`, { method: "POST", body: JSON.stringify({ confirm_stock_changes: confirmStockChanges }), headers: tenantAuthorization(organizationId, accessToken) }),
  cancelInventoryCount: (id: string, organizationId: string, accessToken: string) =>
    request<InventoryCount>(`/api/v1/inventory/counts/${id}/cancel`, { method: "POST", headers: tenantAuthorization(organizationId, accessToken) }),
  listInventoryTransfers: (organizationId: string, accessToken: string, filters: { warehouseId?: string; locationId?: string; status?: string } = {}) =>
    request<InventoryTransfer[]>(`/api/v1/inventory/transfers?${operationFilters(filters)}`, { headers: tenantAuthorization(organizationId, accessToken) }),
  getInventoryTransfer: (id: string, organizationId: string, accessToken: string) =>
    request<InventoryTransfer>(`/api/v1/inventory/transfers/${id}`, { headers: tenantAuthorization(organizationId, accessToken) }),
  createInventoryTransfer: (
    input: { source_warehouse_id: string; destination_warehouse_id: string; occurred_at: string; note?: string | null; lines: Array<{ inventory_item_id: string; quantity: string; unit: InventoryUnitCode }> },
    organizationId: string,
    accessToken: string,
  ) => request<InventoryTransfer>("/api/v1/inventory/transfers", { method: "POST", body: JSON.stringify(input), headers: tenantAuthorization(organizationId, accessToken) }),
  postInventoryTransfer: (id: string, organizationId: string, accessToken: string) =>
    request<InventoryTransfer>(`/api/v1/inventory/transfers/${id}/post`, { method: "POST", headers: tenantAuthorization(organizationId, accessToken) }),
  reverseInventoryTransfer: (id: string, organizationId: string, accessToken: string) =>
    request<InventoryTransfer>(`/api/v1/inventory/transfers/${id}/reverse`, { method: "POST", headers: tenantAuthorization(organizationId, accessToken) }),
  listMenuCategories: (organizationId: string, accessToken: string) =>
    request<MenuCategory[]>("/api/v1/menu/categories", {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  createMenuCategory: (
    input: { name: string; sort_order?: number },
    organizationId: string,
    accessToken: string,
  ) =>
    request<MenuCategory>("/api/v1/menu/categories", {
      method: "POST",
      body: JSON.stringify(input),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  updateMenuCategory: (
    categoryId: string,
    input: { name?: string; sort_order?: number; is_active?: boolean },
    organizationId: string,
    accessToken: string,
  ) =>
    request<MenuCategory>(`/api/v1/menu/categories/${categoryId}`, {
      method: "PATCH",
      body: JSON.stringify(input),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  archiveMenuCategory: (
    categoryId: string,
    organizationId: string,
    accessToken: string,
  ) =>
    request<MenuCategory>(`/api/v1/menu/categories/${categoryId}/archive`, {
      method: "POST",
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  listMenuProducts: (
    organizationId: string,
    accessToken: string,
    filters: {
      categoryId?: string;
      status?: ProductStatus | "";
      search?: string;
      locationId?: string;
    } = {},
  ) =>
    request<MenuProduct[]>(`/api/v1/menu/products?${menuProductFilters(filters)}`, {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  getMenuProduct: (
    productId: string,
    organizationId: string,
    accessToken: string,
    locationId?: string,
  ) =>
    request<MenuProduct>(
      `/api/v1/menu/products/${productId}${locationId ? `?${new URLSearchParams({ location_id: locationId })}` : ""}`,
      { headers: tenantAuthorization(organizationId, accessToken) },
    ),
  createMenuProduct: (
    input: CreateProductInput,
    organizationId: string,
    accessToken: string,
  ) =>
    request<MenuProduct>("/api/v1/menu/products", {
      method: "POST",
      body: JSON.stringify(input),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  updateMenuProduct: (
    productId: string,
    input: Partial<Pick<MenuProduct, "category_id" | "name" | "description" | "image_url" | "status">>,
    organizationId: string,
    accessToken: string,
  ) =>
    request<MenuProduct>(`/api/v1/menu/products/${productId}`, {
      method: "PATCH",
      body: JSON.stringify(input),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  archiveMenuProduct: (
    productId: string,
    organizationId: string,
    accessToken: string,
  ) =>
    request<MenuProduct>(`/api/v1/menu/products/${productId}/archive`, {
      method: "POST",
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  createProductVariant: (
    productId: string,
    input: {
      name: string;
      sku?: string | null;
      base_price_minor: string;
      is_default?: boolean;
      sort_order?: number;
    },
    organizationId: string,
    accessToken: string,
  ) =>
    request<ProductVariant>(`/api/v1/menu/products/${productId}/variants`, {
      method: "POST",
      body: JSON.stringify(input),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  updateProductVariant: (
    variantId: string,
    input: Partial<Pick<ProductVariant, "name" | "sku" | "base_price_minor" | "is_default" | "sort_order" | "status">>,
    organizationId: string,
    accessToken: string,
  ) =>
    request<ProductVariant>(`/api/v1/menu/variants/${variantId}`, {
      method: "PATCH",
      body: JSON.stringify(input),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  archiveProductVariant: (
    variantId: string,
    organizationId: string,
    accessToken: string,
  ) =>
    request<ProductVariant>(`/api/v1/menu/variants/${variantId}/archive`, {
      method: "POST",
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  setVariantPrice: (
    variantId: string,
    locationId: string,
    priceMinor: string | null,
    organizationId: string,
    accessToken: string,
  ) =>
    request<unknown>(`/api/v1/menu/variants/${variantId}/prices/${locationId}`, {
      method: "PUT",
      body: JSON.stringify({ price_minor: priceMinor }),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  setProductLocation: (
    productId: string,
    locationId: string,
    input: { is_available: boolean; is_visible: boolean },
    organizationId: string,
    accessToken: string,
  ) =>
    request<unknown>(`/api/v1/menu/products/${productId}/locations/${locationId}`, {
      method: "PUT",
      body: JSON.stringify(input),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  getVariantRecipe: (
    variantId: string,
    organizationId: string,
    accessToken: string,
  ) =>
    request<Recipe>(`/api/v1/menu/variants/${variantId}/recipe`, {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  listModifierGroups: (
    variantId: string,
    organizationId: string,
    accessToken: string,
    locationId?: string,
  ) =>
    request<ModifierGroup[]>(
      `/api/v1/menu/variants/${variantId}/modifier-groups${locationId ? `?${new URLSearchParams({ location_id: locationId })}` : ""}`,
      { headers: tenantAuthorization(organizationId, accessToken) },
    ),
  createModifierGroup: (
    variantId: string,
    input: Pick<ModifierGroup, "name" | "selection_type" | "min_selections" | "max_selections" | "sort_order">,
    organizationId: string,
    accessToken: string,
  ) =>
    request<ModifierGroup>(`/api/v1/menu/variants/${variantId}/modifier-groups`, {
      method: "POST",
      body: JSON.stringify(input),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  updateModifierGroup: (
    groupId: string,
    input: Partial<Pick<ModifierGroup, "name" | "selection_type" | "min_selections" | "max_selections" | "sort_order">>,
    organizationId: string,
    accessToken: string,
  ) =>
    request<ModifierGroup>(`/api/v1/menu/modifier-groups/${groupId}`, {
      method: "PATCH",
      body: JSON.stringify(input),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  archiveModifierGroup: (groupId: string, organizationId: string, accessToken: string) =>
    request<ModifierGroup>(`/api/v1/menu/modifier-groups/${groupId}/archive`, {
      method: "POST",
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  createModifierOption: (
    groupId: string,
    input: Pick<ModifierOption, "name" | "base_price_delta_minor" | "is_default" | "sort_order">,
    organizationId: string,
    accessToken: string,
  ) =>
    request<ModifierOption>(`/api/v1/menu/modifier-groups/${groupId}/options`, {
      method: "POST",
      body: JSON.stringify(input),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  updateModifierOption: (
    optionId: string,
    input: Partial<Pick<ModifierOption, "name" | "base_price_delta_minor" | "is_default" | "sort_order">>,
    organizationId: string,
    accessToken: string,
  ) =>
    request<ModifierOption>(`/api/v1/menu/modifier-options/${optionId}`, {
      method: "PATCH",
      body: JSON.stringify(input),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  archiveModifierOption: (optionId: string, organizationId: string, accessToken: string) =>
    request<ModifierOption>(`/api/v1/menu/modifier-options/${optionId}/archive`, {
      method: "POST",
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  setModifierComponents: (
    optionId: string,
    components: Array<Pick<ModifierOptionComponent, "inventory_item_id" | "quantity_delta" | "sort_order"> & { unit: InventoryUnitCode }>,
    organizationId: string,
    accessToken: string,
  ) =>
    request<ModifierOption>(`/api/v1/menu/modifier-options/${optionId}/components`, {
      method: "PUT",
      body: JSON.stringify({ components }),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  setModifierLocationPrice: (
    optionId: string,
    locationId: string,
    priceDeltaMinor: string,
    organizationId: string,
    accessToken: string,
  ) =>
    request<ModifierOption>(`/api/v1/menu/modifier-options/${optionId}/prices/${locationId}`, {
      method: "PUT",
      body: JSON.stringify({ price_delta_minor: priceDeltaMinor }),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  deleteModifierLocationPrice: (
    optionId: string,
    locationId: string,
    organizationId: string,
    accessToken: string,
  ) =>
    request<void>(`/api/v1/menu/modifier-options/${optionId}/prices/${locationId}`, {
      method: "DELETE",
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  setModifierLocationAvailability: (
    optionId: string,
    locationId: string,
    isAvailable: boolean,
    organizationId: string,
    accessToken: string,
  ) =>
    request<ModifierOption>(`/api/v1/menu/modifier-options/${optionId}/locations/${locationId}`, {
      method: "PUT",
      body: JSON.stringify({ is_available: isAvailable }),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  previewCustomization: (
    variantId: string,
    selectedOptionIds: string[],
    warehouseId: string,
    locationId: string,
    organizationId: string,
    accessToken: string,
  ) =>
    request<CustomizationPreview>(
      `/api/v1/menu/variants/${variantId}/customization-preview?${new URLSearchParams({ warehouse_id: warehouseId, location_id: locationId })}`,
      {
        method: "POST",
        body: JSON.stringify({ selected_option_ids: selectedOptionIds }),
        headers: tenantAuthorization(organizationId, accessToken),
      },
    ),
  setVariantRecipe: (
    variantId: string,
    input: {
      name?: string;
      yield_quantity?: string;
      components: Array<{
        inventory_item_id: string;
        quantity: string;
        unit: InventoryUnitCode;
        sort_order?: number;
      }>;
    },
    organizationId: string,
    accessToken: string,
  ) =>
    request<Recipe>(`/api/v1/menu/variants/${variantId}/recipe`, {
      method: "PUT",
      body: JSON.stringify(input),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  getVariantCost: (
    variantId: string,
    warehouseId: string,
    organizationId: string,
    accessToken: string,
    locationId?: string,
  ) => {
    const params = new URLSearchParams({ warehouse_id: warehouseId });
    if (locationId) params.set("location_id", locationId);
    return request<RecipeCost>(`/api/v1/menu/variants/${variantId}/cost?${params}`, {
      headers: tenantAuthorization(organizationId, accessToken),
    });
  },
  getMenuCosts: (
    warehouseId: string,
    organizationId: string,
    accessToken: string,
    locationId?: string,
  ) => {
    const params = new URLSearchParams({ warehouse_id: warehouseId });
    if (locationId) params.set("location_id", locationId);
    return request<MenuCostSummary>(`/api/v1/menu/costs?${params}`, {
      headers: tenantAuthorization(organizationId, accessToken),
    });
  },
  getMenu: (locationId: string, organizationId: string, accessToken: string) =>
    request<MenuReadModel>(`/api/v1/menu?${new URLSearchParams({ location_id: locationId })}`, {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  listPosRegisters: (locationId: string, organizationId: string, accessToken: string) =>
    request<PosRegister[]>(
      `/api/v1/sales/registers?${new URLSearchParams({ location_id: locationId })}`,
      { headers: tenantAuthorization(organizationId, accessToken) },
    ),
  listPosWarehouses: (locationId: string, organizationId: string, accessToken: string) =>
    request<PosWarehouseChoice[]>(
      `/api/v1/sales/warehouses?${new URLSearchParams({ location_id: locationId })}`,
      { headers: tenantAuthorization(organizationId, accessToken) },
    ),
  createPosRegister: (
    input: { location_id: string; name: string },
    organizationId: string,
    accessToken: string,
  ) => request<PosRegister>("/api/v1/sales/registers", {
    method: "POST",
    body: JSON.stringify(input),
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  updatePosRegister: (
    registerId: string,
    input: { name: string },
    organizationId: string,
    accessToken: string,
  ) => request<PosRegister>(`/api/v1/sales/registers/${registerId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  deactivatePosRegister: (
    registerId: string,
    organizationId: string,
    accessToken: string,
  ) => request<PosRegister>(`/api/v1/sales/registers/${registerId}/deactivate`, {
    method: "POST",
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  getCurrentRegisterShift: (
    registerId: string,
    organizationId: string,
    accessToken: string,
  ) => request<RegisterShift | null>(
    `/api/v1/sales/shifts/current?${new URLSearchParams({ register_id: registerId })}`,
    { headers: tenantAuthorization(organizationId, accessToken) },
  ),
  openRegisterShift: (
    input: { register_id: string; warehouse_id: string },
    organizationId: string,
    accessToken: string,
  ) => request<RegisterShift>("/api/v1/sales/shifts/open", {
    method: "POST",
    body: JSON.stringify(input),
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  closeRegisterShift: (
    shiftId: string,
    organizationId: string,
    accessToken: string,
  ) => request<RegisterShift>(`/api/v1/sales/shifts/${shiftId}/close`, {
    method: "POST",
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  listSalesOrders: (
    organizationId: string,
    accessToken: string,
    filters: { locationId?: string; shiftId?: string; status?: SalesOrderStatus } = {},
  ) => request<SalesOrder[]>(`/api/v1/sales/orders?${salesOrderFilters(filters)}`, {
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  getSalesOrder: (orderId: string, organizationId: string, accessToken: string) =>
    request<SalesOrder>(`/api/v1/sales/orders/${orderId}`, {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  createSalesOrder: (
    input: {
      client_order_id: string;
      shift_id: string;
      order_type: SalesOrderType;
      guest_count?: number | null;
      table_label?: string | null;
      note?: string | null;
    },
    organizationId: string,
    accessToken: string,
  ) => request<SalesOrder>("/api/v1/sales/orders", {
    method: "POST",
    body: JSON.stringify(input),
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  updateSalesOrder: (
    orderId: string,
    input: Partial<Pick<SalesOrder, "order_type" | "guest_count" | "table_label" | "note">>,
    organizationId: string,
    accessToken: string,
  ) => request<SalesOrder>(`/api/v1/sales/orders/${orderId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  cancelSalesOrder: (
    orderId: string,
    reason: string,
    organizationId: string,
    accessToken: string,
  ) => request<SalesOrder>(`/api/v1/sales/orders/${orderId}/cancel`, {
    method: "POST",
    body: JSON.stringify({ reason }),
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  addSalesOrderItem: (
    orderId: string,
    input: {
      client_item_id: string;
      variant_id: string;
      selected_option_ids: string[];
      quantity: number;
      note?: string | null;
    },
    organizationId: string,
    accessToken: string,
  ) => request<SalesOrder>(`/api/v1/sales/orders/${orderId}/items`, {
    method: "POST",
    body: JSON.stringify(input),
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  updateSalesOrderItem: (
    orderId: string,
    itemId: string,
    input: { quantity?: number; note?: string | null },
    organizationId: string,
    accessToken: string,
  ) => request<SalesOrder>(`/api/v1/sales/orders/${orderId}/items/${itemId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  configureSalesOrderItem: (
    orderId: string,
    itemId: string,
    selectedOptionIds: string[],
    organizationId: string,
    accessToken: string,
  ) => request<SalesOrder>(
    `/api/v1/sales/orders/${orderId}/items/${itemId}/configuration`,
    {
      method: "PUT",
      body: JSON.stringify({ selected_option_ids: selectedOptionIds }),
      headers: tenantAuthorization(organizationId, accessToken),
    },
  ),
  removeSalesOrderItem: (
    orderId: string,
    itemId: string,
    organizationId: string,
    accessToken: string,
  ) => request<SalesOrder>(`/api/v1/sales/orders/${orderId}/items/${itemId}`, {
    method: "DELETE",
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  completePayment: (
    orderId: string,
    input: { client_payment_id: string; lines: PaymentLineInput[] },
    organizationId: string,
    accessToken: string,
  ) => request<Payment>(`/api/v1/payments/orders/${orderId}/complete`, {
    method: "POST",
    body: JSON.stringify(input),
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  listPaymentMethods: (organizationId: string, accessToken: string) =>
    request<PaymentMethodChoice[]>("/api/v1/payments/methods", {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  listPayments: (
    organizationId: string,
    accessToken: string,
    filters: { locationId?: string; shiftId?: string; dateFrom?: string; dateTo?: string; method?: PaymentMethod } = {},
  ) => request<Payment[]>(`/api/v1/payments?${operationFilters(filters)}`, {
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  previewRefund: (input: RefundPreviewRequest, organizationId: string, accessToken: string) =>
    request<RefundPreview>("/api/v1/refunds/preview", {
      method: "POST",
      body: JSON.stringify(input),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  createRefund: (
    input: RefundPreviewRequest & { client_refund_id: string },
    organizationId: string,
    accessToken: string,
  ) => request<Refund>("/api/v1/refunds", {
    method: "POST",
    body: JSON.stringify(input),
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  listRefunds: (
    organizationId: string,
    accessToken: string,
    filters: { locationId?: string; orderId?: string; paymentId?: string; status?: RefundStatus; dateFrom?: string; dateTo?: string } = {},
  ) => request<Refund[]>(`/api/v1/refunds?${operationFilters(filters)}`, {
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  getRefund: (refundId: string, organizationId: string, accessToken: string) =>
    request<Refund>(`/api/v1/refunds/${refundId}`, {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  listPaymentRefunds: (paymentId: string, organizationId: string, accessToken: string) =>
    request<Refund[]>(`/api/v1/payments/${paymentId}/refunds`, {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  getFiscalTaxProfile: (organizationId: string, accessToken: string) =>
    request<FiscalTaxProfile>("/api/v1/fiscal/tax-profile", {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  updateFiscalTaxProfile: (
    input: Pick<FiscalTaxProfile, "country_code" | "tax_regime_code" | "vat_registered" | "default_vat_rate" | "effective_from">,
    organizationId: string,
    accessToken: string,
  ) => request<FiscalTaxProfile>("/api/v1/fiscal/tax-profile", {
    method: "PUT",
    body: JSON.stringify(input),
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  getFiscalVariantProfile: (variantId: string, organizationId: string, accessToken: string) =>
    request<FiscalVariantProfile>(`/api/v1/fiscal/variants/${variantId}`, {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  updateFiscalVariantProfile: (
    variantId: string,
    input: Pick<FiscalVariantProfile, "fiscal_name" | "nkt_code" | "nkt_code_type" | "fiscal_unit_code" | "vat_rate_override" | "requires_marking">,
    organizationId: string,
    accessToken: string,
  ) => request<FiscalVariantProfile>(`/api/v1/fiscal/variants/${variantId}`, {
    method: "PUT",
    body: JSON.stringify(input),
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  getFiscalReadiness: (organizationId: string, accessToken: string) =>
    request<FiscalReadiness>("/api/v1/fiscal/readiness", {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  getOnboardingStatus: (organizationId: string, accessToken: string) =>
    request<OnboardingStatusResponse>("/api/v1/onboarding/status", {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  getOnboardingCapabilities: (organizationId: string, accessToken: string) =>
    request<OnboardingCapabilities>("/api/v1/onboarding/capabilities", {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  bootstrapOnboarding: (
    input: { warehouse_name?: string; register_name?: string },
    organizationId: string,
    accessToken: string,
  ) => request<OnboardingBootstrapResponse>("/api/v1/onboarding/bootstrap", {
    method: "POST",
    body: JSON.stringify(input),
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  dismissOnboarding: (organizationId: string, accessToken: string) =>
    request<OnboardingStatusResponse>("/api/v1/onboarding/dismiss", {
      method: "POST",
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  listOnboardingTemplates: (organizationId: string, accessToken: string) =>
    request<OnboardingTemplateList>("/api/v1/onboarding/templates", {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  downloadOnboardingSpreadsheet: (organizationId: string, accessToken: string) =>
    requestBlob("/api/v1/onboarding/templates/spreadsheet", {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  previewOnboardingTemplate: (
    code: string,
    input: {
      client_import_id: string;
      version: number;
      location_id: string;
      options: OnboardingTemplateOptions;
    },
    organizationId: string,
    accessToken: string,
  ) => request<OnboardingImportRun>(`/api/v1/onboarding/templates/${encodeURIComponent(code)}/preview`, {
    method: "POST",
    body: JSON.stringify(input),
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  listOnboardingImports: (organizationId: string, accessToken: string) =>
    request<OnboardingImportList>("/api/v1/onboarding/imports?limit=50&offset=0", {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  getOnboardingImport: (id: string, organizationId: string, accessToken: string) =>
    request<OnboardingImportRun>(`/api/v1/onboarding/imports/${id}`, {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  uploadOnboardingImport: (
    input: {
      clientImportId: string;
      locationId: string;
      sourceType: OnboardingUploadSourceType;
      file: File;
      mapping?: Record<string, string>;
    },
    organizationId: string,
    accessToken: string,
  ) => {
    const body = new FormData();
    body.set("client_import_id", input.clientImportId);
    body.set("location_id", input.locationId);
    body.set("source_type", input.sourceType);
    body.set("file", input.file);
    if (input.mapping && Object.keys(input.mapping).length > 0) {
      body.set("mapping_json", JSON.stringify(input.mapping));
    }
    return request<OnboardingImportRun>("/api/v1/onboarding/imports", {
      method: "POST",
      body,
      headers: tenantAuthorization(organizationId, accessToken),
    });
  },
  inspectOnboardingImport: (
    input: { sourceType: OnboardingUploadSourceType; file: File },
    organizationId: string,
    accessToken: string,
  ) => {
    const body = new FormData();
    body.set("source_type", input.sourceType);
    body.set("file", input.file);
    return request<OnboardingImportInspect>("/api/v1/onboarding/imports/inspect", {
      method: "POST",
      body,
      headers: tenantAuthorization(organizationId, accessToken),
    });
  },
  updateOnboardingImportEntity: (
    importId: string,
    entityId: string,
    input: { resolution: OnboardingImportResolution; target_id?: string | null; payload?: Record<string, unknown> },
    organizationId: string,
    accessToken: string,
  ) => request<OnboardingImportEntity>(`/api/v1/onboarding/imports/${importId}/entities/${entityId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  validateOnboardingImport: (id: string, organizationId: string, accessToken: string) =>
    request<OnboardingImportValidation>(`/api/v1/onboarding/imports/${id}/validate`, {
      method: "POST",
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  applyOnboardingImport: (id: string, organizationId: string, accessToken: string) =>
    request<OnboardingImportRun>(`/api/v1/onboarding/imports/${id}/apply`, {
      method: "POST",
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  cancelOnboardingImport: (id: string, organizationId: string, accessToken: string) =>
    request<OnboardingImportRun>(`/api/v1/onboarding/imports/${id}/cancel`, {
      method: "POST",
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  resumeOnboardingImport: (id: string, organizationId: string, accessToken: string) =>
    request<OnboardingImportRun>(`/api/v1/onboarding/imports/${id}/resume`, {
      method: "POST",
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  updateOnboardingPrices: (
    id: string,
    rows: Array<{ entity_id: string; price_minor: string }>,
    organizationId: string,
    accessToken: string,
  ) => request<OnboardingImportValidation>(`/api/v1/onboarding/imports/${id}/prices`, {
    method: "PUT",
    body: JSON.stringify({ rows }),
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  activateReadyOnboardingProducts: (
    id: string,
    input: { product_ids: string[]; confirm_starter_recipes_reviewed: boolean },
    organizationId: string,
    accessToken: string,
  ) => request<OnboardingActivationResult>(`/api/v1/onboarding/imports/${id}/activate-ready`, {
    method: "POST",
    body: JSON.stringify(input),
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  searchNkt: (query: string, organizationId: string, accessToken: string, limit = 20) => {
    const params = new URLSearchParams({ query, limit: String(limit) });
    return request<NktProduct[]>(`/api/v1/fiscal/nkt/search?${params}`, {
      headers: tenantAuthorization(organizationId, accessToken),
    });
  },
  getNktByNtin: (ntin: string, organizationId: string, accessToken: string) =>
    request<NktProduct>(`/api/v1/fiscal/nkt/ntin/${encodeURIComponent(ntin)}`, {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  getNktByGtin: (gtin: string, organizationId: string, accessToken: string) =>
    request<NktProduct[]>(`/api/v1/fiscal/nkt/gtin/${encodeURIComponent(gtin)}`, {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  linkFiscalVariantNkt: (variantId: string, ntin: string, organizationId: string, accessToken: string) =>
    request<FiscalVariantProfile>(`/api/v1/fiscal/variants/${variantId}/nkt`, {
      method: "PUT",
      body: JSON.stringify({ ntin }),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  refreshFiscalVariantNkt: (variantId: string, organizationId: string, accessToken: string) =>
    request<FiscalVariantProfile>(`/api/v1/fiscal/variants/${variantId}/nkt/refresh`, {
      method: "POST",
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  getFiscalOperations: (locationId: string, organizationId: string, accessToken: string) =>
    request<FiscalOperations>(`/api/v1/fiscal/operations?location_id=${encodeURIComponent(locationId)}`, {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  listFiscalReceipts: (
    organizationId: string,
    accessToken: string,
    filters: { locationId?: string; status?: FiscalReceiptStatus | ""; limit?: string; offset?: string } = {},
  ) => request<FiscalReceiptList>(`/api/v1/fiscal/receipts?${operationFilters(filters)}`, {
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  getFiscalReceipt: (receiptId: string, organizationId: string, accessToken: string) =>
    request<FiscalReceipt>(`/api/v1/fiscal/receipts/${receiptId}`, {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  retryFiscalReceipt: (receiptId: string, organizationId: string, accessToken: string) =>
    request<FiscalReceipt>(`/api/v1/fiscal/receipts/${receiptId}/retry`, {
      method: "POST",
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  reconcileFiscalReceipt: (receiptId: string, organizationId: string, accessToken: string) =>
    request<FiscalReceipt>(`/api/v1/fiscal/receipts/${receiptId}/reconcile`, {
      method: "POST",
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  getFiscalEnforcement: (locationId: string, organizationId: string, accessToken: string) =>
    request<FiscalEnforcement>(`/api/v1/fiscal/locations/${locationId}/enforcement`, {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  updateFiscalEnforcement: (locationId: string, mode: FiscalEnforcementMode, organizationId: string, accessToken: string) =>
    request<FiscalEnforcement>(`/api/v1/fiscal/locations/${locationId}/enforcement`, {
      method: "PUT",
      body: JSON.stringify({ mode }),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  getFiscalGoLiveReadiness: (locationId: string, organizationId: string, accessToken: string) =>
    request<FiscalGoLiveReadiness>(`/api/v1/fiscal/locations/${locationId}/go-live-readiness`, {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  listFiscalRoutes: (locationId: string, organizationId: string, accessToken: string) =>
    request<FiscalRoute[]>(`/api/v1/fiscal/routes?location_id=${encodeURIComponent(locationId)}`, {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  createFiscalRoute: (
    input: Pick<FiscalRoute, "location_id" | "register_id" | "provider_connection_id" | "source_mode" | "is_active">,
    organizationId: string,
    accessToken: string,
  ) => request<FiscalRoute>("/api/v1/fiscal/routes", {
    method: "POST",
    body: JSON.stringify(input),
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  updateFiscalRoute: (
    routeId: string,
    input: Pick<FiscalRoute, "is_active">,
    organizationId: string,
    accessToken: string,
  ) => request<FiscalRoute>(`/api/v1/fiscal/routes/${routeId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  listTerminalBindings: (registerId: string, organizationId: string, accessToken: string) =>
    request<TerminalBinding[]>(`/api/v1/payments/terminal-bindings?register_id=${encodeURIComponent(registerId)}`, {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  createTerminalBinding: (
    input: Pick<TerminalBinding, "connection_id" | "location_id" | "register_id" | "provider_code"> & { external_terminal_id?: string | null; is_active?: boolean },
    organizationId: string,
    accessToken: string,
  ) => request<TerminalBinding>("/api/v1/payments/terminal-bindings", {
    method: "POST",
    body: JSON.stringify(input),
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  updateTerminalBinding: (
    bindingId: string,
    input: Partial<Pick<TerminalBinding, "external_terminal_id" | "transport_config" | "is_active">>,
    organizationId: string,
    accessToken: string,
  ) => request<TerminalBinding>(`/api/v1/payments/terminal-bindings/${bindingId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  createExternalPaymentAttempt: (
    input: Pick<ExternalPaymentAttempt, "client_attempt_id" | "order_id" | "register_id" | "pos_device_id" | "connection_id" | "provider_code" | "method" | "amount_minor" | "currency_code">,
    organizationId: string,
    accessToken: string,
  ) => request<ExternalPaymentAttempt>("/api/v1/payments/external-attempts", {
    method: "POST",
    body: JSON.stringify(input),
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  getExternalPaymentAttempt: (attemptId: string, organizationId: string, accessToken: string) =>
    request<ExternalPaymentAttempt>(`/api/v1/payments/external-attempts/${attemptId}`, {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  startExternalPaymentAttempt: (attemptId: string, organizationId: string, accessToken: string) =>
    request<ExternalPaymentAttempt>(`/api/v1/payments/external-attempts/${attemptId}/start`, {
      method: "POST",
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  reconcileExternalPaymentAttempt: (attemptId: string, organizationId: string, accessToken: string) =>
    request<ExternalPaymentAttempt>(`/api/v1/payments/external-attempts/${attemptId}/reconcile`, {
      method: "POST",
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  listSuppliers: (
    organizationId: string,
    accessToken: string,
    includeInactive = false,
  ) =>
    request<Supplier[]>(`/api/v1/suppliers?include_inactive=${includeInactive}`, {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  getSupplier: (supplierId: string, organizationId: string, accessToken: string) =>
    request<Supplier>(`/api/v1/suppliers/${supplierId}`, {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  createSupplier: (input: SupplierInput, organizationId: string, accessToken: string) =>
    request<Supplier>("/api/v1/suppliers", {
      method: "POST",
      body: JSON.stringify(input),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  updateSupplier: (
    supplierId: string,
    input: Partial<SupplierInput>,
    organizationId: string,
    accessToken: string,
  ) =>
    request<Supplier>(`/api/v1/suppliers/${supplierId}`, {
      method: "PATCH",
      body: JSON.stringify(input),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  deactivateSupplier: (supplierId: string, organizationId: string, accessToken: string) =>
    request<Supplier>(`/api/v1/suppliers/${supplierId}/deactivate`, {
      method: "POST",
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  listPurchaseOrders: (
    organizationId: string,
    accessToken: string,
    filters: {
      supplierId?: string;
      locationId?: string;
      warehouseId?: string;
      status?: PurchaseOrderStatus | "";
      dateFrom?: string;
      dateTo?: string;
    } = {},
  ) =>
    request<PurchaseOrder[]>(`/api/v1/purchasing/orders?${purchasingFilters(filters)}`, {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  getPurchaseOrder: (orderId: string, organizationId: string, accessToken: string) =>
    request<PurchaseOrder>(`/api/v1/purchasing/orders/${orderId}`, {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  createPurchaseOrder: (
    input: PurchaseOrderInput,
    organizationId: string,
    accessToken: string,
  ) =>
    request<PurchaseOrder>("/api/v1/purchasing/orders", {
      method: "POST",
      body: JSON.stringify(input),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  updatePurchaseOrder: (
    orderId: string,
    input: Partial<PurchaseOrderInput>,
    organizationId: string,
    accessToken: string,
  ) =>
    request<PurchaseOrder>(`/api/v1/purchasing/orders/${orderId}`, {
      method: "PATCH",
      body: JSON.stringify(input),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  submitPurchaseOrder: (orderId: string, organizationId: string, accessToken: string) =>
    request<PurchaseOrder>(`/api/v1/purchasing/orders/${orderId}/submit`, {
      method: "POST",
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  cancelPurchaseOrder: (orderId: string, organizationId: string, accessToken: string) =>
    request<PurchaseOrder>(`/api/v1/purchasing/orders/${orderId}/cancel`, {
      method: "POST",
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  listGoodsReceipts: (
    organizationId: string,
    accessToken: string,
    filters: { purchaseOrderId?: string; supplierId?: string; status?: GoodsReceiptStatus | "" } = {},
  ) =>
    request<GoodsReceipt[]>(`/api/v1/purchasing/receipts?${receiptFilters(filters)}`, {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  getGoodsReceipt: (receiptId: string, organizationId: string, accessToken: string) =>
    request<GoodsReceipt>(`/api/v1/purchasing/receipts/${receiptId}`, {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  createGoodsReceipt: (
    input: GoodsReceiptInput,
    organizationId: string,
    accessToken: string,
  ) =>
    request<GoodsReceipt>("/api/v1/purchasing/receipts", {
      method: "POST",
      body: JSON.stringify(input),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  createOrderReceipt: (
    orderId: string,
    input: Omit<GoodsReceiptInput, "purchase_order_id" | "supplier_id" | "location_id" | "warehouse_id">,
    organizationId: string,
    accessToken: string,
  ) =>
    request<GoodsReceipt>(`/api/v1/purchasing/orders/${orderId}/receipts`, {
      method: "POST",
      body: JSON.stringify(input),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  updateGoodsReceipt: (
    receiptId: string,
    input: Partial<GoodsReceiptInput>,
    organizationId: string,
    accessToken: string,
  ) =>
    request<GoodsReceipt>(`/api/v1/purchasing/receipts/${receiptId}`, {
      method: "PATCH",
      body: JSON.stringify(input),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  postGoodsReceipt: (
    receiptId: string,
    confirmOverReceipt: boolean,
    organizationId: string,
    accessToken: string,
  ) =>
    request<GoodsReceipt>(`/api/v1/purchasing/receipts/${receiptId}/post`, {
      method: "POST",
      body: JSON.stringify({ confirm_over_receipt: confirmOverReceipt }),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  reverseGoodsReceipt: (receiptId: string, organizationId: string, accessToken: string) =>
    request<GoodsReceipt>(`/api/v1/purchasing/receipts/${receiptId}/reverse`, {
      method: "POST",
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  listSupplierReturns: (organizationId: string, accessToken: string, filters: { supplierId?: string; warehouseId?: string; locationId?: string; goodsReceiptId?: string; status?: string } = {}) =>
    request<SupplierReturn[]>(`/api/v1/purchasing/returns?${operationFilters(filters)}`, { headers: tenantAuthorization(organizationId, accessToken) }),
  getSupplierReturn: (id: string, organizationId: string, accessToken: string) =>
    request<SupplierReturn>(`/api/v1/purchasing/returns/${id}`, { headers: tenantAuthorization(organizationId, accessToken) }),
  createSupplierReturn: (
    input: { supplier_id: string; location_id: string; goods_receipt_id?: string | null; warehouse_id: string; returned_at: string; document_number?: string | null; note?: string | null; lines: Array<{ goods_receipt_line_id?: string | null; inventory_item_id: string; quantity: string; purchase_unit?: string; unit_multiplier?: string; unit_price?: string }> },
    organizationId: string,
    accessToken: string,
  ) => request<SupplierReturn>("/api/v1/purchasing/returns", { method: "POST", body: JSON.stringify(input), headers: tenantAuthorization(organizationId, accessToken) }),
  postSupplierReturn: (id: string, organizationId: string, accessToken: string) =>
    request<SupplierReturn>(`/api/v1/purchasing/returns/${id}/post`, { method: "POST", headers: tenantAuthorization(organizationId, accessToken) }),
  reverseSupplierReturn: (id: string, organizationId: string, accessToken: string) =>
    request<SupplierReturn>(`/api/v1/purchasing/returns/${id}/reverse`, { method: "POST", headers: tenantAuthorization(organizationId, accessToken) }),
  getDashboardOverview: (
    organizationId: string,
    accessToken: string,
    filters: {
      period: DashboardPeriod;
      locationId?: string;
      dateFrom?: string;
      dateTo?: string;
    },
  ) => request<DashboardOverview>(`/api/v1/dashboard/overview?${operationFilters(filters)}`, {
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  getAnalyticsOverview: (organizationId: string, accessToken: string, filters: AnalyticsRangeFilters) =>
    request<AnalyticsOverview>(`/api/v1/analytics/overview?${operationFilters(filters)}`, { headers: tenantAuthorization(organizationId, accessToken) }),
  getAnalyticsProducts: (organizationId: string, accessToken: string, filters: AnalyticsRangeFilters & { groupBy: AnalyticsGroupBy; sortBy: AnalyticsProductSort; limit?: string }) =>
    request<AnalyticsProducts>(`/api/v1/analytics/products?${operationFilters(filters)}`, { headers: tenantAuthorization(organizationId, accessToken) }),
  getAnalyticsAbc: (organizationId: string, accessToken: string, filters: AnalyticsRangeFilters) =>
    request<AnalyticsAbc>(`/api/v1/analytics/products/abc?${operationFilters(filters)}`, { headers: tenantAuthorization(organizationId, accessToken) }),
  getAnalyticsMenuEngineering: (organizationId: string, accessToken: string, filters: AnalyticsRangeFilters) =>
    request<AnalyticsMenuEngineering>(`/api/v1/analytics/menu-engineering?${operationFilters(filters)}`, { headers: tenantAuthorization(organizationId, accessToken) }),
  getAnalyticsHours: (organizationId: string, accessToken: string, filters: AnalyticsRangeFilters & { metric: AnalyticsHourMetric }) =>
    request<AnalyticsHours>(`/api/v1/analytics/hours?${operationFilters(filters)}`, { headers: tenantAuthorization(organizationId, accessToken) }),
  getAnalyticsInventoryConsumption: (organizationId: string, accessToken: string, filters: AnalyticsRangeFilters & { warehouseId?: string; inventoryItemId?: string }) =>
    request<AnalyticsInventoryConsumption>(`/api/v1/analytics/inventory-consumption?${operationFilters(filters)}`, { headers: tenantAuthorization(organizationId, accessToken) }),
  getAnalyticsLocations: (organizationId: string, accessToken: string, filters: Omit<AnalyticsRangeFilters, "locationId">) =>
    request<AnalyticsLocations>(`/api/v1/analytics/locations?${operationFilters(filters)}`, { headers: tenantAuthorization(organizationId, accessToken) }),
  listIntegrationProviders: (organizationId: string, accessToken: string) =>
    request<IntegrationProvider[]>("/api/v1/integrations/providers", {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  listIntegrationConnections: (organizationId: string, accessToken: string) =>
    request<IntegrationConnection[]>("/api/v1/integrations/connections", {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  createIntegrationConnection: (
    input: IntegrationConnectionInput,
    organizationId: string,
    accessToken: string,
  ) => request<IntegrationConnection>("/api/v1/integrations/connections", {
    method: "POST",
    body: JSON.stringify(input),
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  getIntegrationConnection: (id: string, organizationId: string, accessToken: string) =>
    request<IntegrationConnection>(`/api/v1/integrations/connections/${id}`, {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  updateIntegrationConnection: (
    id: string,
    input: Partial<Pick<IntegrationConnectionInput, "display_name" | "config" | "credentials">>,
    organizationId: string,
    accessToken: string,
  ) => request<IntegrationConnection>(`/api/v1/integrations/connections/${id}`, {
    method: "PATCH",
    body: JSON.stringify(input),
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  testIntegrationConnection: (id: string, organizationId: string, accessToken: string) =>
    request<IntegrationConnection>(`/api/v1/integrations/connections/${id}/test`, {
      method: "POST",
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  disconnectIntegrationConnection: (id: string, organizationId: string, accessToken: string) =>
    request<IntegrationConnection>(`/api/v1/integrations/connections/${id}/disconnect`, {
      method: "POST",
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  setIntegrationLocationBinding: (
    connectionId: string,
    locationId: string,
    input: {
      capability: IntegrationCapability;
      external_location_id?: string;
      settings?: Record<string, unknown>;
      is_active?: boolean;
    },
    organizationId: string,
    accessToken: string,
  ) => request<IntegrationLocationBinding>(
    `/api/v1/integrations/connections/${connectionId}/locations/${locationId}`,
    {
      method: "PUT",
      body: JSON.stringify(input),
      headers: tenantAuthorization(organizationId, accessToken),
    },
  ),
  deleteIntegrationLocationBinding: (
    connectionId: string,
    locationId: string,
    capability: IntegrationCapability,
    organizationId: string,
    accessToken: string,
  ) => request<void>(
    `/api/v1/integrations/connections/${connectionId}/locations/${locationId}?capability=${capability}`,
    { method: "DELETE", headers: tenantAuthorization(organizationId, accessToken) },
  ),
  listIntegrationJobs: (
    organizationId: string,
    accessToken: string,
    filters: {
      connectionId?: string;
      status?: IntegrationJobStatus | "";
      jobType?: string;
      dateFrom?: string;
      dateTo?: string;
      limit?: string;
      offset?: string;
    } = {},
  ) => request<IntegrationJobList>(
    `/api/v1/integrations/jobs?${operationFilters(filters)}`,
    { headers: tenantAuthorization(organizationId, accessToken) },
  ),
  retryIntegrationJob: (id: string, organizationId: string, accessToken: string) =>
    request<IntegrationJob>(`/api/v1/integrations/jobs/${id}/retry`, {
      method: "POST",
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  getFinancePnl: (
    organizationId: string,
    accessToken: string,
    filters: { dateFrom: string; dateTo: string; locationId?: string },
  ) => request<FinancePnl>(`/api/v1/finance/pnl?${operationFilters(filters)}`, {
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  getFinancePnlBreakdown: (
    organizationId: string,
    accessToken: string,
    filters: { dateFrom: string; dateTo: string; locationId?: string },
  ) => request<FinancePnlBreakdown>(`/api/v1/finance/pnl/breakdown?${operationFilters(filters)}`, {
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  getFinanceCashFlow: (
    organizationId: string,
    accessToken: string,
    filters: { dateFrom: string; dateTo: string; locationId?: string },
  ) => request<FinanceCashFlow>(`/api/v1/finance/cash-flow?${operationFilters(filters)}`, {
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  listExpenseCategories: (organizationId: string, accessToken: string) =>
    request<ExpenseCategory[]>("/api/v1/finance/expense-categories", {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  createExpenseCategory: (
    input: { name: string; sort_order?: number },
    organizationId: string,
    accessToken: string,
  ) => request<ExpenseCategory>("/api/v1/finance/expense-categories", {
    method: "POST",
    body: JSON.stringify(input),
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  updateExpenseCategory: (
    id: string,
    input: { name?: string; sort_order?: number },
    organizationId: string,
    accessToken: string,
  ) => request<ExpenseCategory>(`/api/v1/finance/expense-categories/${id}`, {
    method: "PATCH",
    body: JSON.stringify(input),
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  deactivateExpenseCategory: (id: string, organizationId: string, accessToken: string) =>
    request<ExpenseCategory>(`/api/v1/finance/expense-categories/${id}/deactivate`, {
      method: "POST",
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  listExpenses: (organizationId: string, accessToken: string) =>
    request<Expense[]>("/api/v1/finance/expenses", {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  getExpense: (id: string, organizationId: string, accessToken: string) =>
    request<Expense>(`/api/v1/finance/expenses/${id}`, {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  createExpense: (input: ExpenseInput, organizationId: string, accessToken: string) =>
    request<Expense>("/api/v1/finance/expenses", {
      method: "POST",
      body: JSON.stringify(input),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  updateExpense: (id: string, input: Partial<ExpenseInput>, organizationId: string, accessToken: string) =>
    request<Expense>(`/api/v1/finance/expenses/${id}`, {
      method: "PATCH",
      body: JSON.stringify(input),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  postExpense: (id: string, organizationId: string, accessToken: string) =>
    request<Expense>(`/api/v1/finance/expenses/${id}/post`, {
      method: "POST",
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  reverseExpense: (id: string, organizationId: string, accessToken: string) =>
    request<Expense>(`/api/v1/finance/expenses/${id}/reverse`, {
      method: "POST",
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  listCashAccounts: (organizationId: string, accessToken: string) =>
    request<CashAccount[]>("/api/v1/finance/accounts", {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  createCashAccount: (
    input: { location_id?: string | null; name: string; type: CashAccountType; opening_balance_minor?: string },
    organizationId: string,
    accessToken: string,
  ) => request<CashAccount>("/api/v1/finance/accounts", {
    method: "POST",
    body: JSON.stringify(input),
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  updateCashAccount: (
    id: string,
    input: { name?: string; type?: CashAccountType },
    organizationId: string,
    accessToken: string,
  ) => request<CashAccount>(`/api/v1/finance/accounts/${id}`, {
    method: "PATCH",
    body: JSON.stringify(input),
    headers: tenantAuthorization(organizationId, accessToken),
  }),
  deactivateCashAccount: (id: string, organizationId: string, accessToken: string) =>
    request<CashAccount>(`/api/v1/finance/accounts/${id}/deactivate`, {
      method: "POST",
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  listCashMovements: (organizationId: string, accessToken: string) =>
    request<CashMovement[]>("/api/v1/finance/cash-movements", {
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  createCashMovement: (input: CashMovementInput, organizationId: string, accessToken: string) =>
    request<CashMovement>("/api/v1/finance/cash-movements", {
      method: "POST",
      body: JSON.stringify(input),
      headers: tenantAuthorization(organizationId, accessToken),
    }),
  reverseCashMovement: (id: string, organizationId: string, accessToken: string) =>
    request<CashMovement>(`/api/v1/finance/cash-movements/${id}/reverse`, {
      method: "POST",
      headers: tenantAuthorization(organizationId, accessToken),
    }),
};

function authorization(accessToken: string) {
  return { authorization: `Bearer ${accessToken}` };
}

function tenantAuthorization(organizationId: string, accessToken: string) {
  return {
    ...authorization(accessToken),
    "X-Organization-ID": organizationId,
  };
}

function inventoryFilters(filters: {
  warehouseId?: string;
  locationId?: string;
  itemId?: string;
}) {
  const params = new URLSearchParams();
  if (filters.warehouseId) params.set("warehouse_id", filters.warehouseId);
  if (filters.locationId) params.set("location_id", filters.locationId);
  if (filters.itemId) params.set("item_id", filters.itemId);
  return params.toString();
}

function operationFilters(filters: Record<string, string | undefined>) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (!value) continue;
    params.set(key.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`), value);
  }
  return params.toString();
}

function menuProductFilters(filters: {
  categoryId?: string;
  status?: ProductStatus | "";
  search?: string;
  locationId?: string;
}) {
  const params = new URLSearchParams();
  if (filters.categoryId) params.set("category_id", filters.categoryId);
  if (filters.status) params.set("status", filters.status);
  if (filters.search) params.set("search", filters.search);
  if (filters.locationId) params.set("location_id", filters.locationId);
  return params.toString();
}

function purchasingFilters(filters: {
  supplierId?: string;
  locationId?: string;
  warehouseId?: string;
  status?: PurchaseOrderStatus | "";
  dateFrom?: string;
  dateTo?: string;
}) {
  const params = new URLSearchParams();
  if (filters.supplierId) params.set("supplier_id", filters.supplierId);
  if (filters.locationId) params.set("location_id", filters.locationId);
  if (filters.warehouseId) params.set("warehouse_id", filters.warehouseId);
  if (filters.status) params.set("status", filters.status);
  if (filters.dateFrom) params.set("date_from", filters.dateFrom);
  if (filters.dateTo) params.set("date_to", filters.dateTo);
  return params.toString();
}

function receiptFilters(filters: {
  purchaseOrderId?: string;
  supplierId?: string;
  status?: GoodsReceiptStatus | "";
}) {
  const params = new URLSearchParams();
  if (filters.purchaseOrderId) params.set("purchase_order_id", filters.purchaseOrderId);
  if (filters.supplierId) params.set("supplier_id", filters.supplierId);
  if (filters.status) params.set("status", filters.status);
  return params.toString();
}

function salesOrderFilters(filters: {
  locationId?: string;
  shiftId?: string;
  status?: SalesOrderStatus;
}) {
  const params = new URLSearchParams();
  if (filters.locationId) params.set("location_id", filters.locationId);
  if (filters.shiftId) params.set("shift_id", filters.shiftId);
  if (filters.status) params.set("status", filters.status);
  return params.toString();
}
