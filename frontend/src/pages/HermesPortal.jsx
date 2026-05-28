import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';

function HermesPortal() {
  const [url, setUrl] = useState('http://localhost:3000');
  const [screenshot, setScreenshot] = useState(null);
  const [timestamp, setTimestamp] = useState(null);
  const [size, setSize] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [refreshInterval, setRefreshInterval] = useState(30);

  // Take screenshot
  const handleTakeScreenshot = useCallback(async () => {
    if (!url.trim()) {
      setError('Please enter a valid URL');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const response = await axios.get('/api/portal/screenshot', {
        params: { url: url.trim() }
      });

      const { screenshot: screenshotData, timestamp: ts, size: sz } = response.data;
      setScreenshot(screenshotData);
      setTimestamp(ts);
      setSize(sz);
    } catch (err) {
      setError(
        err.response?.data?.error ||
        err.message ||
        'Failed to capture screenshot. Please check the URL and try again.'
      );
      setScreenshot(null);
      setTimestamp(null);
      setSize(null);
    } finally {
      setLoading(false);
    }
  }, [url]);

  // Auto-refresh effect
  useEffect(() => {
    if (!autoRefresh) return;

    const timer = setInterval(() => {
      handleTakeScreenshot();
    }, refreshInterval * 1000);

    return () => clearInterval(timer);
  }, [autoRefresh, refreshInterval, handleTakeScreenshot]);

  return (
    <div className="min-h-screen bg-gray-900 text-white p-6">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-4xl font-bold text-green-400 mb-2">🌐 Hermes Portal</h1>
          <p className="text-gray-400">Capture and monitor website screenshots in real-time</p>
        </div>

        {/* Control Panel */}
        <div className="bg-gray-800 rounded-lg p-6 mb-8 border border-gray-700">
          {/* URL Input */}
          <div className="mb-6">
            <label className="block text-sm font-semibold text-gray-300 mb-2">
              Website URL
            </label>
            <input
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onKeyPress={(e) => e.key === 'Enter' && handleTakeScreenshot()}
              placeholder="http://localhost:3000"
              className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded text-white placeholder-gray-400 focus:outline-none focus:border-green-500 transition"
            />
            <p className="text-xs text-gray-400 mt-1">
              Enter the full URL including protocol (http:// or https://)
            </p>
          </div>

          {/* Button and Controls */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
            {/* Take Screenshot Button */}
            <button
              onClick={handleTakeScreenshot}
              disabled={loading}
              className="flex items-center justify-center gap-2 bg-green-600 hover:bg-green-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white font-semibold py-3 rounded-lg transition"
            >
              {loading ? (
                <>
                  <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></div>
                  <span>Capturing...</span>
                </>
              ) : (
                <>
                  <span>📸</span>
                  <span>Take Screenshot</span>
                </>
              )}
            </button>

            {/* Auto-Refresh Toggle */}
            <div className="flex items-center gap-4 bg-gray-700 rounded-lg p-3">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={autoRefresh}
                  onChange={(e) => setAutoRefresh(e.target.checked)}
                  className="w-4 h-4 cursor-pointer"
                />
                <span className="text-sm font-medium">Auto-Refresh</span>
              </label>
            </div>
          </div>

          {/* Refresh Interval Slider */}
          {autoRefresh && (
            <div className="mb-6">
              <label className="block text-sm font-semibold text-gray-300 mb-2">
                Refresh Interval: <span className="text-green-400">{refreshInterval}s</span>
              </label>
              <input
                type="range"
                min="5"
                max="30"
                value={refreshInterval}
                onChange={(e) => setRefreshInterval(parseInt(e.target.value))}
                className="w-full h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer"
              />
              <div className="flex justify-between text-xs text-gray-400 mt-1">
                <span>5s</span>
                <span>30s</span>
              </div>
            </div>
          )}

          {/* Screenshot Info */}
          {(timestamp || size) && (
            <div className="bg-gray-900 rounded p-4 border border-gray-600">
              <div className="grid grid-cols-2 gap-4">
                {timestamp && (
                  <div>
                    <p className="text-xs text-gray-400">Last Captured</p>
                    <p className="text-sm font-mono text-green-400">{timestamp}</p>
                  </div>
                )}
                {size && (
                  <div>
                    <p className="text-xs text-gray-400">Image Size</p>
                    <p className="text-sm font-mono text-green-400">
                      {(size / 1024).toFixed(2)} KB
                    </p>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Error Display */}
        {error && (
          <div className="bg-red-900 border border-red-700 rounded-lg p-4 mb-8">
            <div className="flex items-start gap-3">
              <span className="text-2xl">⚠️</span>
              <div className="flex-1">
                <p className="font-semibold text-red-200 mb-2">Error</p>
                <p className="text-sm text-red-100 mb-3">{error}</p>
                <button
                  onClick={handleTakeScreenshot}
                  className="bg-red-700 hover:bg-red-800 text-white text-sm font-medium py-2 px-4 rounded transition"
                >
                  🔄 Retry
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Screenshot Display */}
        {screenshot && (
          <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
            <div className="flex items-center gap-2 mb-4">
              <h2 className="text-xl font-semibold text-green-400">📷 Screenshot</h2>
              {autoRefresh && (
                <span className="text-xs bg-green-900 text-green-200 px-2 py-1 rounded animate-pulse">
                  Auto-refreshing every {refreshInterval}s
                </span>
              )}
            </div>

            <div className="bg-gray-900 rounded border border-gray-600 overflow-hidden">
              <img
                src={screenshot}
                alt="Website screenshot"
                className="w-full h-auto"
                style={{ maxHeight: '600px', objectFit: 'contain' }}
              />
            </div>

            <div className="mt-4 flex gap-2">
              <button
                onClick={() => {
                  const a = document.createElement('a');
                  a.href = screenshot;
                  a.download = `screenshot-${new Date().getTime()}.png`;
                  a.click();
                }}
                className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white font-medium py-2 px-4 rounded transition"
              >
                <span>⬇️</span>
                <span>Download</span>
              </button>
              <button
                onClick={() => {
                  navigator.clipboard.writeText(screenshot);
                  alert('Screenshot data copied to clipboard!');
                }}
                className="flex items-center gap-2 bg-gray-700 hover:bg-gray-600 text-white font-medium py-2 px-4 rounded transition"
              >
                <span>📋</span>
                <span>Copy Data</span>
              </button>
            </div>
          </div>
        )}

        {/* Empty State */}
        {!screenshot && !loading && (
          <div className="bg-gray-800 rounded-lg p-16 border border-gray-700 text-center">
            <div className="text-5xl mb-4">🖼️</div>
            <h3 className="text-xl font-semibold text-gray-300 mb-2">No Screenshot Yet</h3>
            <p className="text-gray-400">
              Enter a URL above and click "Take Screenshot" to capture a website image
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

export default HermesPortal;