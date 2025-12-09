'use client';

import { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import { FavoriteItem, AnalysisResult } from '@/lib/types';
import { useFavorites } from '@/hooks/useFavorites';

interface AnalysisViewProps {
  favorite: FavoriteItem;
  onClose: () => void;
}

type AnalysisStatus = 'pending' | 'processing' | 'completed' | 'failed';

export function AnalysisView({ favorite, onClose }: AnalysisViewProps) {
  const { getAnalysis } = useFavorites();
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [images, setImages] = useState<string[]>([]);
  const [status, setStatus] = useState<AnalysisStatus>(favorite.analysis_status || 'pending');
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const loadAnalysis = async () => {
      try {
        const result = await getAnalysis(favorite.property_id);
        if (result) {
          setAnalysis(result.analysis_result);
          setImages(result.property_images || []);
          setStatus(result.analysis_status as AnalysisStatus);
        }
      } catch (error) {
        console.error('Failed to load analysis:', error);
      } finally {
        setIsLoading(false);
      }
    };

    loadAnalysis();
  }, [favorite.property_id, getAnalysis]);

  const summary = favorite.property_summary;

  const formatPrice = (price: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      maximumFractionDigits: 0,
    }).format(price);
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg w-full max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="p-4 border-b flex justify-between items-start">
          <div>
            <h2 className="text-xl font-bold">{summary.address}</h2>
            <p className="text-gray-600">
              {summary.city}, {summary.state} | {formatPrice(summary.price)}
            </p>
            <p className="text-sm text-gray-500">
              {summary.beds} bed | {summary.baths} bath | {summary.size_sqft?.toLocaleString()} sqft
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-2xl"
          >
            &times;
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto p-4">
          {/* Images */}
          {images.length > 0 && (
            <div className="mb-6 flex gap-2 overflow-x-auto pb-2">
              {images.map((url, index) => (
                <img
                  key={index}
                  src={url}
                  alt={`Property ${index + 1}`}
                  className="h-32 w-auto rounded object-cover flex-shrink-0"
                />
              ))}
            </div>
          )}

          {/* Analysis */}
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
              <span className="ml-2">Loading analysis...</span>
            </div>
          ) : status === 'pending' || status === 'processing' ? (
            <div className="bg-yellow-50 border border-yellow-200 text-yellow-800 p-4 rounded">
              <h3 className="font-bold mb-2">Analysis in Progress</h3>
              <p>The AI is analyzing this property. Please check back in a few minutes.</p>
            </div>
          ) : status === 'failed' ? (
            <div className="bg-red-50 border border-red-200 text-red-800 p-4 rounded">
              <h3 className="font-bold mb-2">Analysis Failed</h3>
              <p>There was an error analyzing this property. Please try again later.</p>
            </div>
          ) : analysis ? (
            <div className="analysis-content prose max-w-none">
              <ReactMarkdown>
                {analysis.analysis_markdown || analysis.analysis_text || 'No analysis available'}
              </ReactMarkdown>
            </div>
          ) : (
            <div className="text-gray-500 text-center py-8">
              No analysis available yet.
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t flex justify-between">
          {summary.listing_url && (
            <a
              href={summary.listing_url}
              target="_blank"
              rel="noopener noreferrer"
              className="px-4 py-2 text-blue-600 hover:bg-blue-50 rounded"
            >
              View Listing
            </a>
          )}
          <button
            onClick={onClose}
            className="px-4 py-2 bg-gray-200 text-gray-800 rounded hover:bg-gray-300"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
