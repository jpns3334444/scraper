'use client';

import { useState } from 'react';
import { PropertyGrid } from '@/components/PropertyGrid';
import { FilterBar, Filters } from '@/components/FilterBar';
import { useProperties } from '@/hooks/useProperties';

export default function HomePage() {
  const [filters, setFilters] = useState<Filters>({ sort: 'date_desc' });
  const { properties, isLoading, isError, refresh } = useProperties({
    city: filters.city,
    minPrice: filters.minPrice,
    maxPrice: filters.maxPrice,
    minBeds: filters.minBeds,
    sort: filters.sort,
    limit: 100,
  });

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h1 className="text-2xl font-bold">Properties</h1>
        <button
          onClick={() => refresh()}
          className="px-4 py-2 text-sm text-blue-600 hover:bg-blue-50 rounded"
        >
          Refresh
        </button>
      </div>

      <FilterBar onFilterChange={setFilters} />

      {isError && (
        <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-4">
          Error loading properties. Please try again.
        </div>
      )}

      <div className="mb-4 text-sm text-gray-500">
        {properties.length} properties found
      </div>

      <PropertyGrid properties={properties} isLoading={isLoading} />
    </div>
  );
}
