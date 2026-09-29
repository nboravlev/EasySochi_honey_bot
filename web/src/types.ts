// Форматы ответов API (bot/api/schemas.py). Деньги приходят строкой «1500.00».

export interface Location {
  id: number;
  name: string;
  address: string;
  latitude: number | null;
  longitude: number | null;
  opening_hours: string | null;
}

export interface Shop {
  id: number;
  slug: string;
  name: string;
  phone: string | null;
  locations: Location[];
}

export interface ShopRef {
  id: number;
  name: string;
}

export interface ProductType {
  id: number;
  name: string;
}

export interface Offer {
  id: number; // product_size_id
  size: string; // кг: «0.5»
  price: string;
}

export interface Product {
  id: number;
  name: string;
  description: string | null;
  type: ProductType;
  shop: ShopRef;
  photos: string[];
  offers: Offer[];
}

export interface Catalog {
  shop: Shop | null; // null — маркетплейс
  types: ProductType[];
  products: Product[];
}

export interface Config {
  bot_url: string | null;
  marketplace: boolean;
}

export interface Me {
  id: number;
  first_name: string | null;
  phone: string | null;
}

export type OrderStatusCode =
  | "created"
  | "processing"
  | "ready"
  | "customer_notified"
  | "received"
  | "declined";

export interface Order {
  id: number;
  status: { code: OrderStatusCode; title: string };
  product_name: string;
  size: string;
  quantity: number;
  total: string;
  comment: string | null;
  decline_reason: string | null;
  created_at: string;
  pickup: Location | null;
  shop: ShopRef;
}
