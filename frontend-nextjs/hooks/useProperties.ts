'use client';

import useSWR from 'swr';
import { api } from '@/lib/api';
import { Property } from '@/lib/types';

interface UsePropertiesOptions {
  city?: string;
  minPrice?: number;
  maxPrice?: number;
  minBeds?: number;
  sort?: string;
  limit?: number;
}

export function useProperties(options: UsePropertiesOptions = {}) {
  const params: Record<string, string> = {};

  if (options.city) params.city = options.city;
  if (options.minPrice) params.min_price = String(options.minPrice);
  if (options.maxPrice) params.max_price = String(options.maxPrice);
  if (options.minBeds) params.min_beds = String(options.minBeds);
  if (options.sort) params.sort = options.sort;
  if (options.limit) params.limit = String(options.limit);

  const key = ['properties', JSON.stringify(params)];

  const { data, error, isLoading, mutate } = useSWR(
    key,
    () => api.getProperties(params),
    {
      revalidateOnFocus: false,
      dedupingInterval: 60000,
    }
  );

  return {
    properties: data?.items || [],
    cursor: data?.cursor,
    isLoading,
    isError: !!error,
    error,
    refresh: mutate,
  };
}
