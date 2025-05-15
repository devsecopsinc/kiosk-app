import React, { useEffect, useState } from 'react';

// Define interfaces for component props and state
interface MediaData {
  mediaId: string;
  url: string;
  contentType: string;
  filename: string;
  createdAt: string;
}

type Config = {
  apiBaseUrl: string;
};

// Main App component
function App() {
  // State for media data and loading state
  const [mediaData, setMediaData] = useState<MediaData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Get configuration from different sources
  const getConfig = async (): Promise<Config> => {
    console.log('Initializing app config');

    try {
      // Try loading config from config.json
      const configResponse = await fetch('/config.json');
      if (configResponse.ok) {
        const config = await configResponse.json();
        console.log('Loaded config:', config);
        return config;
      }
    } catch (error) {
      console.warn('Failed to load config.json:', error);
    }

    // Default config
    return {
      apiBaseUrl: '/api/v1'
    };
  };

  useEffect(() => {
    const loadMediaFromUrl = async () => {
      setLoading(true);
      setError(null);

      try {
        const appConfig = await getConfig();
        console.log('App configuration loaded:', appConfig);

        // Check if media ID is in URL
        const urlParams = new URLSearchParams(window.location.search);
        const id = urlParams.get('id');
        console.log('Media ID from URL:', id);

        if (id) {
          fetchMediaData(id, appConfig.apiBaseUrl);
        } else {
          setLoading(false);
          setError('No media ID provided');
        }
      } catch (err) {
        console.error('Error loading media from URL:', err);
        setLoading(false);
        setError('Failed to initialize app');
      }
    };

    loadMediaFromUrl();
  }, []);

  const fetchMediaData = async (id: string, apiBaseUrl: string) => {
    setLoading(true);
    setError(null);

    try {
      // With UUID format there should be no special characters,
      // but we'll still use encodeURIComponent for safety
      const encodedId = encodeURIComponent(id);

      console.log('Fetching media data using API URL:', apiBaseUrl);
      console.log('Media ID:', id);

      // Use relative path if apiBaseUrl starts with slash, otherwise use full URL
      const apiUrl = apiBaseUrl.startsWith('/')
        ? `${window.location.origin}${apiBaseUrl}`
        : apiBaseUrl;

      console.log('Using API URL:', apiUrl);
      const response = await fetch(`${apiUrl}/media/${encodedId}`);

      if (!response.ok) {
        throw new Error(`HTTP error! Status: ${response.status}`);
      }

      const data = await response.json();
      setMediaData(data);
    } catch (err) {
      console.error('Error fetching media data:', err);
      setError('Failed to fetch');
    } finally {
      setLoading(false);
    }
  };

  const renderMedia = () => {
    if (!mediaData) return null;

    const { url, contentType, filename } = mediaData;

    // Check if it's an image type
    const isImage = contentType.startsWith('image/');

    return (
      <div style={{ marginTop: '20px', width: '100%', maxWidth: '800px' }}>
        <h2>{filename}</h2>

        {isImage && (
          <div style={{ margin: '20px 0' }}>
            <img
              src={url}
              alt={filename}
              style={{ maxWidth: '100%', maxHeight: '500px' }}
            />
          </div>
        )}

        <div style={{ marginTop: '20px' }}>
          <a
            href={url}
            download={filename}
            style={{
              backgroundColor: '#4CAF50',
              color: 'white',
              padding: '10px 20px',
              textDecoration: 'none',
              borderRadius: '4px',
              fontSize: '16px',
              display: 'inline-block'
            }}
          >
            Download {filename}
          </a>
        </div>
      </div>
    );
  };

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      minHeight: '100vh',
      padding: '20px',
      textAlign: 'center'
    }}>
      <h1>Media Sharing App</h1>

      {!mediaData && (
        <p>No media ID provided. Please scan a QR code or use a direct link to access media.</p>
      )}

      {loading && <p>Loading media data...</p>}

      {error && (
        <div style={{ color: 'red', margin: '20px 0' }}>
          <p>Error: {error}</p>
        </div>
      )}

      {renderMedia()}
    </div>
  );
}

export default App; 