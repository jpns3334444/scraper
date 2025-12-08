'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useAuthContext } from './AuthProvider';
import { useState } from 'react';
import { AuthModal } from './AuthModal';

export function Navigation() {
  const pathname = usePathname();
  const { user, isAuthenticated, logout } = useAuthContext();
  const [showAuthModal, setShowAuthModal] = useState(false);

  const navItems = [
    { href: '/', label: 'Properties' },
    { href: '/favorites', label: 'Favorites' },
    { href: '/hidden', label: 'Hidden' },
  ];

  return (
    <>
      <nav className="bg-white shadow-md">
        <div className="container mx-auto px-4">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center space-x-8">
              <Link href="/" className="text-xl font-bold text-blue-600">
                Real Estate AI
              </Link>
              <div className="flex space-x-4">
                {navItems.map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`px-3 py-2 rounded-md text-sm font-medium ${
                      pathname === item.href
                        ? 'bg-blue-100 text-blue-700'
                        : 'text-gray-600 hover:bg-gray-100'
                    }`}
                  >
                    {item.label}
                  </Link>
                ))}
              </div>
            </div>

            <div className="flex items-center">
              {isAuthenticated ? (
                <div className="flex items-center space-x-4">
                  <span className="text-sm text-gray-600">{user?.email}</span>
                  <button
                    onClick={logout}
                    className="px-3 py-2 text-sm text-gray-600 hover:text-gray-800"
                  >
                    Logout
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setShowAuthModal(true)}
                  className="px-4 py-2 bg-blue-600 text-white rounded-md text-sm font-medium hover:bg-blue-700"
                >
                  Sign In
                </button>
              )}
            </div>
          </div>
        </div>
      </nav>

      {showAuthModal && (
        <AuthModal onClose={() => setShowAuthModal(false)} />
      )}
    </>
  );
}
