import { PropertiesResponse, FavoritesResponse, HiddenResponse, AnalysisResult, PropertySummary } from './types';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'https://your-api-gateway-url.execute-api.us-east-1.amazonaws.com/prod';

interface FetchOptions {
  userEmail?: string;
}

async function fetchWithAuth(endpoint: string, options: RequestInit & FetchOptions = {}) {
  const { userEmail, ...fetchOptions } = options;

  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...(fetchOptions.headers || {}),
  };

  if (userEmail) {
    (headers as Record<string, string>)['X-User-Email'] = userEmail;
  }

  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    ...fetchOptions,
    headers,
  });

  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }

  return response.json();
}

export const api = {
  // Properties
  async getProperties(params: Record<string, string> = {}): Promise<PropertiesResponse> {
    const queryString = new URLSearchParams(params).toString();
    const endpoint = queryString ? `/properties?${queryString}` : '/properties';
    return fetchWithAuth(endpoint);
  },

  // Favorites
  async getFavorites(userEmail: string): Promise<FavoritesResponse> {
    return fetchWithAuth(`/favorites/user/${encodeURIComponent(userEmail)}`, { userEmail });
  },

  async addFavorite(userEmail: string, propertyId: string): Promise<{ success: boolean }> {
    return fetchWithAuth('/favorites', {
      method: 'POST',
      userEmail,
      body: JSON.stringify({ property_id: propertyId }),
    });
  },

  async removeFavorite(userEmail: string, propertyId: string): Promise<{ success: boolean }> {
    return fetchWithAuth(`/favorites/${encodeURIComponent(propertyId)}`, {
      method: 'DELETE',
      userEmail,
    });
  },

  async getFavoriteAnalysis(userEmail: string, propertyId: string): Promise<{
    analysis_result: AnalysisResult;
    analysis_status: string;
    property_images: string[];
    property_summary: PropertySummary;
  }> {
    return fetchWithAuth(
      `/favorites/analysis/${encodeURIComponent(userEmail)}/${encodeURIComponent(propertyId)}`,
      { userEmail }
    );
  },

  // Hidden
  async getHidden(userEmail: string): Promise<HiddenResponse> {
    return fetchWithAuth(`/hidden/user/${encodeURIComponent(userEmail)}`, { userEmail });
  },

  async addHidden(userEmail: string, propertyId: string): Promise<{ success: boolean }> {
    return fetchWithAuth('/hidden', {
      method: 'POST',
      userEmail,
      body: JSON.stringify({ property_id: propertyId }),
    });
  },

  async removeHidden(userEmail: string, propertyId: string): Promise<{ success: boolean }> {
    return fetchWithAuth(`/hidden/${encodeURIComponent(propertyId)}`, {
      method: 'DELETE',
      userEmail,
    });
  },
};
