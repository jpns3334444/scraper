export interface Property {
  property_id: string;
  listing_url: string;
  price: number;
  price_per_sqft: number;
  size_sqft: number;
  beds: number;
  baths: number;
  address: string;
  city: string;
  state: string;
  zip_code: string;
  property_type: string;
  year_built: number;
  lot_size_sqft: number;
  lot_size_acres: number;
  hoa_fee: number;
  mls_id: string;
  image_url?: string;
  image_urls?: string[];
  image_count: number;
  days_on_market: number | null;
  city_median_price_per_sqft: number;
  city_discount_pct: number;
  first_seen_date: string;
  analysis_date: string;
  is_favorited?: boolean;
}

export interface PropertySummary {
  price: number;
  city: string;
  state: string;
  address: string;
  size_sqft: number;
  beds: number;
  baths: number;
  property_type: string;
  image_url?: string;
  listing_url?: string;
}

export interface FavoriteItem {
  user_id: string;
  property_id: string;
  preference_type: 'favorite' | 'hidden';
  created_at: string;
  property_summary: PropertySummary;
  analysis_status?: 'pending' | 'processing' | 'completed' | 'failed';
  analysis_result?: AnalysisResult;
}

export interface AnalysisResult {
  analysis_markdown: string;
  verdict: string;
  analysis_text: string;
}

export interface User {
  email: string;
  isAuthenticated: boolean;
}

export interface PropertiesResponse {
  items: Property[];
  cursor: Record<string, any> | null;
  total_in_page: number;
}

export interface FavoritesResponse {
  favorites: FavoriteItem[];
}

export interface HiddenResponse {
  hidden: FavoriteItem[];
}
