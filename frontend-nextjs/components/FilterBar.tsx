'use client';

import { useState } from 'react';

interface FilterBarProps {
  onFilterChange: (filters: Filters) => void;
}

export interface Filters {
  city?: string;
  minPrice?: number;
  maxPrice?: number;
  minBeds?: number;
  sort?: string;
}

export function FilterBar({ onFilterChange }: FilterBarProps) {
  const [filters, setFilters] = useState<Filters>({
    sort: 'date_desc',
  });

  const handleChange = (key: keyof Filters, value: string | number | undefined) => {
    const newFilters = { ...filters, [key]: value };
    setFilters(newFilters);
    onFilterChange(newFilters);
  };

  return (
    <div className="bg-white p-4 rounded-lg shadow-md mb-6">
      <div className="flex flex-wrap gap-4 items-center">
        {/* City filter */}
        <div>
          <label className="block text-xs text-gray-500 mb-1">City</label>
          <input
            type="text"
            placeholder="e.g., Paonia"
            value={filters.city || ''}
            onChange={(e) => handleChange('city', e.target.value || undefined)}
            className="px-3 py-2 border border-gray-300 rounded-md text-sm w-32"
          />
        </div>

        {/* Price range */}
        <div>
          <label className="block text-xs text-gray-500 mb-1">Min Price</label>
          <select
            value={filters.minPrice || ''}
            onChange={(e) => handleChange('minPrice', e.target.value ? Number(e.target.value) : undefined)}
            className="px-3 py-2 border border-gray-300 rounded-md text-sm"
          >
            <option value="">Any</option>
            <option value="100000">$100k+</option>
            <option value="200000">$200k+</option>
            <option value="300000">$300k+</option>
            <option value="500000">$500k+</option>
          </select>
        </div>

        <div>
          <label className="block text-xs text-gray-500 mb-1">Max Price</label>
          <select
            value={filters.maxPrice || ''}
            onChange={(e) => handleChange('maxPrice', e.target.value ? Number(e.target.value) : undefined)}
            className="px-3 py-2 border border-gray-300 rounded-md text-sm"
          >
            <option value="">Any</option>
            <option value="200000">$200k</option>
            <option value="300000">$300k</option>
            <option value="500000">$500k</option>
            <option value="1000000">$1M</option>
          </select>
        </div>

        {/* Beds */}
        <div>
          <label className="block text-xs text-gray-500 mb-1">Beds</label>
          <select
            value={filters.minBeds || ''}
            onChange={(e) => handleChange('minBeds', e.target.value ? Number(e.target.value) : undefined)}
            className="px-3 py-2 border border-gray-300 rounded-md text-sm"
          >
            <option value="">Any</option>
            <option value="1">1+</option>
            <option value="2">2+</option>
            <option value="3">3+</option>
            <option value="4">4+</option>
          </select>
        </div>

        {/* Sort */}
        <div>
          <label className="block text-xs text-gray-500 mb-1">Sort by</label>
          <select
            value={filters.sort || 'date_desc'}
            onChange={(e) => handleChange('sort', e.target.value)}
            className="px-3 py-2 border border-gray-300 rounded-md text-sm"
          >
            <option value="date_desc">Newest</option>
            <option value="price_asc">Price: Low to High</option>
            <option value="price_desc">Price: High to Low</option>
            <option value="price_per_sqft_asc">$/sqft: Low to High</option>
            <option value="days_on_market_desc">Days on Market</option>
          </select>
        </div>
      </div>
    </div>
  );
}
