// Форматы API админки (bot/api/admin/schemas.py).
import type { Location, OrderStatusCode, ShopRef } from "../types";

export type StaffAction = "confirm" | "ready" | "received" | "decline";

export interface AdminMe {
  user_id: number;
  name: string | null;
  is_owner: boolean;
  shop: ShopRef | null;
  via: "telegram" | "session";
}

export interface Customer {
  id: number;
  name: string | null;
  phone: string | null;
  telegram_username: string | null;
  vk_url: string | null;
}

export interface AdminOrder {
  id: number;
  status: { code: OrderStatusCode; title: string };
  shop: ShopRef;
  product_name: string;
  size: string;
  quantity: number;
  total: string;
  comment: string | null;
  decline_reason: string | null;
  created_at: string;
  updated_at: string | null;
  customer: Customer;
  manager: string | null;
  pickup: Location | null;
  actions: StaffAction[];
}

export interface OrderPage {
  items: AdminOrder[];
  total: number;
}

export interface DeliveryResult {
  sent: number;
  queued: number;
  failed: number;
}

export interface Size {
  id: number;
  kg: string;
  package: string | null;
}

export interface ProductType {
  id: number;
  name: string;
}

export interface Reference {
  sizes: Size[];
  types: ProductType[];
}

export interface AdminOffer {
  id: number;
  size_id: number;
  kg: string;
  price: string;
  active: boolean;
}

export type ProductState = "draft" | "published" | "withdrawn";

export interface AdminProduct {
  id: number;
  name: string;
  description: string | null;
  type: ProductType;
  shop: ShopRef;
  state: ProductState;
  offers: AdminOffer[];
  photos: { id: number; url: string | null }[];
  updated_at: string | null;
}

export interface AdminLocation extends Location {
  is_pickup: boolean;
  is_active: boolean;
}

export interface AdminShop {
  id: number;
  slug: string;
  name: string;
  phone: string | null;
  is_active: boolean;
  is_storefront: boolean;
  staff_chat_id: string | null;
  locations: AdminLocation[];
  managers: number;
}

export interface Manager {
  user_id: number;
  name: string | null;
  telegram_id: string | null;
  username: string | null;
  shop: ShopRef | null;
  is_owner: boolean;
}

export interface Bucket {
  count: number;
  total: string;
}

export interface Stats {
  period_days: number | null;
  sales: { name: string; kg: string; total: string }[];
  new: Bucket;
  in_progress: Bucket;
  completed: Bucket;
  declined: Bucket;
  customers: number;
  tasting_waiting: number;
  next_tasting: { starts_at: string; invited: number; going: number; declined: number } | null;
}

export interface QueuedNotification {
  id: number;
  kind: string;
  provider: string;
  status: string;
  attempts: number;
  last_error: string | null;
  created_at: string;
  next_attempt_at: string;
  user_id: number | null;
  shop_id: number | null;
  text: string;
}
