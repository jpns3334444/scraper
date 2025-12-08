'use client';

import { useState } from 'react';
import { useAuthContext } from '@/components/AuthProvider';
import { useFavorites } from '@/hooks/useFavorites';
import { AnalysisView } from '@/components/AnalysisView';
import { FavoriteItem } from '@/lib/types';

export default function FavoritesPage() {
  const { isAuthenticated } = useAuthContext();
  const { favorites, isLoading, removeFavorite, refresh } = useFavorites();
  const [selectedFavorite, setSelectedFavorite] = useState<FavoriteItem | null>(null);

  const formatPrice = (price: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      maximumFractionDigits: 0,
    }).format(price);
  };

  if (!isAuthenticated) {
    return (
      <div className="text-center py-12">
        <h1 className="text-2xl font-bold mb-4">Favorites</h1>
        <p className="text-gray-600 mb-4">Sign in to view your favorite properties.</p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="text-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto" />
        <p className="mt-4 text-gray-600">Loading favorites...</p>
      </div>
    );
  }

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold">Favorites ({favorites.length})</h1>
        <button
          onClick={() => refresh()}
          className="px-4 py-2 text-sm text-blue-600 hover:bg-blue-50 rounded"
        >
          Refresh
        </button>
      </div>

      {favorites.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          No favorites yet. Star properties to add them here.
        </div>
      ) : (
        <div className="space-y-4">
          {favorites.map((fav) => {
            const summary = fav.property_summary;
            return (
              <div
                key={fav.property_id}
                className="bg-white rounded-lg shadow-md p-4 flex items-center gap-4"
              >
                {/* Image */}
                <div className="w-24 h-24 bg-gray-200 rounded overflow-hidden flex-shrink-0">
                  {summary.image_url ? (
                    <img
                      src={summary.image_url}
                      alt={summary.address}
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-gray-400 text-sm">
                      No Image
                    </div>
                  )}
                </div>

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <h3 className="font-bold text-lg">{formatPrice(summary.price || 0)}</h3>
                  <p className="text-gray-600 text-sm truncate">{summary.address}</p>
                  <p className="text-gray-500 text-sm">
                    {summary.city}, {summary.state} | {summary.beds} bed | {summary.baths} bath
                  </p>
                  <div className="mt-1">
                    <span
                      className={`text-xs px-2 py-1 rounded ${
                        fav.analysis_status === 'completed'
                          ? 'bg-green-100 text-green-800'
                          : fav.analysis_status === 'failed'
                          ? 'bg-red-100 text-red-800'
                          : 'bg-yellow-100 text-yellow-800'
                      }`}
                    >
                      {fav.analysis_status || 'pending'}
                    </span>
                  </div>
                </div>

                {/* Actions */}
                <div className="flex flex-col gap-2">
                  <button
                    onClick={() => setSelectedFavorite(fav)}
                    className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700"
                  >
                    View Analysis
                  </button>
                  {summary.listing_url && (
                    <a
                      href={summary.listing_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="px-4 py-2 text-blue-600 border border-blue-600 rounded text-sm text-center hover:bg-blue-50"
                    >
                      View Listing
                    </a>
                  )}
                  <button
                    onClick={() => removeFavorite(fav.property_id)}
                    className="px-4 py-2 text-red-600 text-sm hover:bg-red-50 rounded"
                  >
                    Remove
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {selectedFavorite && (
        <AnalysisView
          favorite={selectedFavorite}
          onClose={() => setSelectedFavorite(null)}
        />
      )}
    </div>
  );
}
