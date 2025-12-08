'use client';

import useSWR from 'swr';
import { api } from '@/lib/api';
import { FavoriteItem } from '@/lib/types';
import { useAuth } from './useAuth';
import { useCallback } from 'react';

export function useFavorites() {
  const { user } = useAuth();
  const userEmail = user?.email;

  const { data, error, isLoading, mutate } = useSWR(
    userEmail ? ['favorites', userEmail] : null,
    () => api.getFavorites(userEmail!),
    {
      revalidateOnFocus: false,
    }
  );

  const addFavorite = useCallback(async (propertyId: string) => {
    if (!userEmail) return;
    await api.addFavorite(userEmail, propertyId);
    mutate();
  }, [userEmail, mutate]);

  const removeFavorite = useCallback(async (propertyId: string) => {
    if (!userEmail) return;
    await api.removeFavorite(userEmail, propertyId);
    mutate();
  }, [userEmail, mutate]);

  const getAnalysis = useCallback(async (propertyId: string) => {
    if (!userEmail) return null;
    return api.getFavoriteAnalysis(userEmail, propertyId);
  }, [userEmail]);

  return {
    favorites: data?.favorites || [],
    isLoading,
    isError: !!error,
    addFavorite,
    removeFavorite,
    getAnalysis,
    refresh: mutate,
  };
}

export function useHidden() {
  const { user } = useAuth();
  const userEmail = user?.email;

  const { data, error, isLoading, mutate } = useSWR(
    userEmail ? ['hidden', userEmail] : null,
    () => api.getHidden(userEmail!),
    {
      revalidateOnFocus: false,
    }
  );

  const addHidden = useCallback(async (propertyId: string) => {
    if (!userEmail) return;
    await api.addHidden(userEmail, propertyId);
    mutate();
  }, [userEmail, mutate]);

  const removeHidden = useCallback(async (propertyId: string) => {
    if (!userEmail) return;
    await api.removeHidden(userEmail, propertyId);
    mutate();
  }, [userEmail, mutate]);

  return {
    hidden: data?.hidden || [],
    isLoading,
    isError: !!error,
    addHidden,
    removeHidden,
    refresh: mutate,
  };
}
