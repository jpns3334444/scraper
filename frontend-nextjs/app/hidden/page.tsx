'use client';

import { useAuthContext } from '@/components/AuthProvider';
import { useHidden } from '@/hooks/useFavorites';

export default function HiddenPage() {
  const { isAuthenticated } = useAuthContext();
  const { hidden, isLoading, removeHidden, refresh } = useHidden();

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
        <h1 className="text-2xl font-bold mb-4">Hidden Properties</h1>
        <p className="text-gray-600 mb-4">Sign in to view your hidden properties.</p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="text-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto" />
        <p className="mt-4 text-gray-600">Loading hidden properties...</p>
      </div>
    );
  }

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold">Hidden Properties ({hidden.length})</h1>
        <button
          onClick={() => refresh()}
          className="px-4 py-2 text-sm text-blue-600 hover:bg-blue-50 rounded"
        >
          Refresh
        </button>
      </div>

      {hidden.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          No hidden properties. Hide properties you're not interested in.
        </div>
      ) : (
        <div className="space-y-4">
          {hidden.map((item) => {
            const summary = item.property_summary;
            return (
              <div
                key={item.property_id}
                className="bg-white rounded-lg shadow-md p-4 flex items-center gap-4 opacity-75"
              >
                {/* Image */}
                <div className="w-20 h-20 bg-gray-200 rounded overflow-hidden flex-shrink-0">
                  {summary.image_url ? (
                    <img
                      src={summary.image_url}
                      alt={summary.address}
                      className="w-full h-full object-cover grayscale"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-gray-400 text-xs">
                      No Image
                    </div>
                  )}
                </div>

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <h3 className="font-bold">{formatPrice(summary.price || 0)}</h3>
                  <p className="text-gray-600 text-sm truncate">{summary.address}</p>
                  <p className="text-gray-500 text-sm">
                    {summary.city}, {summary.state}
                  </p>
                </div>

                {/* Actions */}
                <div>
                  <button
                    onClick={() => removeHidden(item.property_id)}
                    className="px-4 py-2 text-blue-600 text-sm hover:bg-blue-50 rounded"
                  >
                    Unhide
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
