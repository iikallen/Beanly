import type {
  MenuReadModel,
  PaymentLineInput,
  PaymentMethodChoice,
  SalesOrderType,
} from "@/lib/api";

export type OfflineOrderStatus =
  | "OPEN"
  | "CANCELLED_PENDING_SYNC"
  | "PAID_PENDING_SYNC"
  | "SYNCED_OPEN"
  | "SYNCED_CANCELLED"
  | "SYNCED_PAID"
  | "CONFLICT";

export type OfflineOrderItem = {
  id: string;
  client_item_id: string;
  product_id: string;
  product_variant_id: string;
  product_name: string;
  variant_name: string;
  selected_option_ids: string[];
  quantity: number;
  base_price_minor: string;
  modifier_price_minor: string;
  unit_price_minor: string;
  line_total_minor: string;
  note: string | null;
  modifiers: Array<{
    modifier_group_id: string;
    modifier_group_name: string;
    modifier_option_id: string;
    modifier_option_name: string;
    price_delta_minor: string;
  }>;
};

export type OfflinePaymentLine = PaymentLineInput & { external_settlement_confirmed?: boolean };

export type OfflinePayment = {
  client_payment_id: string;
  completed_at: string;
  lines: OfflinePaymentLine[];
};

export type OfflineOrder = {
  id: string;
  client_order_id: string;
  server_order_id: string | null;
  server_version: number | null;
  revision: number;
  last_synced_revision: number;
  catalog_snapshot_id: string;
  session_id: string;
  organization_id: string;
  location_id: string;
  shift_id: string;
  warehouse_id: string;
  offline_display_number: number;
  number: string;
  order_type: SalesOrderType;
  status: OfflineOrderStatus;
  currency_code: string;
  items: OfflineOrderItem[];
  subtotal_minor: string;
  total_minor: string;
  payment: OfflinePayment | null;
  cancel_reason: string | null;
  created_at: string;
  updated_at: string;
  sync_error: string | null;
};

export type PublicCatalogSnapshot = {
  id: string;
  payload_hash: string;
  created_at: string;
  expires_at: string;
  public_payload: MenuReadModel;
};

export type OfflineSession = {
  id: string;
  device_id: string;
  organization_id: string;
  location_id: string;
  register_id: string;
  shift_id: string;
  warehouse_id: string;
  actor_user_id: string;
  catalog_snapshot_id: string;
  status: "ACTIVE" | "CLOSED" | "REVOKED" | "EXPIRED";
  started_at: string;
  expires_at: string;
  last_sync_at: string | null;
  server_time: string;
  clock_offset_ms: number;
  catalog_snapshot: PublicCatalogSnapshot;
  shell: {
    organization_name: string;
    location_name: string;
    register_name: string;
    operator_name: string;
    currency_code: string;
    permissions: string[];
    payment_methods: PaymentMethodChoice[];
  };
};

export type SyncResult = {
  client_order_id: string;
  revision: number;
  status: "SYNCED" | "CONFLICT";
  code?: string;
  server_order_id?: string;
  server_order_number?: number;
  server_version?: number;
  payment_id?: string;
};

export type SyncState = {
  key: "state";
  status: "OFFLINE" | "ONLINE" | "SYNCING" | "ISSUE";
  last_sync_at: string | null;
  error: string | null;
};

export type StorageReadiness = {
  indexedDb: boolean;
  catalog: boolean;
  persistent: boolean;
  device: boolean;
  shell: boolean;
  usage: number;
  quota: number;
};
