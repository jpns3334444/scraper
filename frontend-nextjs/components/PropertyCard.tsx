'use client';

import { Property } from '@/lib/types';
import { useAuthContext } from './AuthProvider';
import { useFavorites, useHidden } from '@/hooks/useFavorites';

interface PropertyCardProps {
  property: Property;
}

export function PropertyCard({ property }: PropertyCardProps) {
  const { isAuthenticated } = useAuthContext();
  const { addFavorite } = useFavorites();
  const { addHidden } = useHidden();

  const formatPrice = (price: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      maximumFractionDigits: 0,
    }).format(price);
  };

  const discountClass = property.city_discount_pct < 0
    ? 'price-below-median'
    : property.city_discount_pct > 5
    ? 'price-above-median'
    : '';

  return (
    <div className="property-card">
      {/* Image */}
      <div className="relative h-48 bg-gray-200">
        {property.image_url ? (
          <img
            src={property.image_url}
            alt={property.address}
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="flex items-center justify-center h-full text-gray-400">
            No Image
          </div>
        )}
        {property.days_on_market !== null && (
          <span className="absolute top-2 left-2 bg-black bg-opacity-70 text-white text-xs px-2 py-1 rounded">
            {property.days_on_market} days
          </span>
        )}
      </div>

      {/* Content */}
      <div className="p-4">
        <div className="flex justify-between items-start mb-2">
          <h3 className="text-lg font-bold">{formatPrice(property.price)}</h3>
          <span className={`text-sm ${discountClass}`}>
            {property.city_discount_pct > 0 ? '+' : ''}
            {property.city_discount_pct?.toFixed(1)}%
          </span>
        </div>

        <p className="text-gray-600 text-sm mb-2">
          {property.beds} bed | {property.baths} bath | {property.size_sqft?.toLocaleString()} sqft
        </p>

        <p className="text-gray-500 text-sm mb-2 truncate" title={property.address}>
          {property.address}
        </p>

        <p className="text-gray-500 text-sm">
          {property.city}, {property.state} {property.zip_code}
        </p>

        <div className="flex justify-between items-center mt-3 pt-3 border-t">
          <span className="text-sm text-gray-500">
            ${property.price_per_sqft?.toFixed(0)}/sqft
          </span>

          <div className="flex space-x-2">
            <a
              href={property.listing_url}
              target="_blank"
              rel="noopener noreferrer"
              className="px-3 py-1 text-sm text-blue-600 hover:bg-blue-50 rounded"
            >
              View
            </a>

            {isAuthenticated && (
              <>
                <button
                  onClick={() => addFavorite(property.property_id)}
                  className="px-3 py-1 text-sm text-green-600 hover:bg-green-50 rounded"
                  title="Add to favorites"
                >
                  ★
                </button>
                <button
                  onClick={() => addHidden(property.property_id)}
                  className="px-3 py-1 text-sm text-gray-400 hover:bg-gray-50 rounded"
                  title="Hide property"
                >
                  ✕
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
