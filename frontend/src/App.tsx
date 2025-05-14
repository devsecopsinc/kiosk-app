import React, { useEffect, useState } from 'react';

// Configuration types
interface AppConfig {
  apiUrl: string;
}

// Get configuration from different sources
const getConfig = async (): Promise<AppConfig> => {
  // Default values
  const defaultConfig: AppConfig = {
    apiUrl: '/api/v1'
  };

  try {
    // Try to load config.json which may be generated during deployment
    const configResponse = await fetch('/config.json');
    if (configResponse.ok) {
      const configData = await configResponse.json();
      console.log('Loaded config from config.json:', configData);
      return { ...defaultConfig, ...configData };
    }
  } catch (err) {
    console.log('Could not load config.json, using environment detection');
  }

  // Try to get API URL from meta tag first (highest priority)
  const apiUrlMeta = document.querySelector('meta[name="api-url"]');
  if (apiUrlMeta && apiUrlMeta.getAttribute('content')) {
    const metaApiUrl = apiUrlMeta.getAttribute('content') || '';
    console.log('Found API URL in meta tag:', metaApiUrl);
    return { ...defaultConfig, apiUrl: metaApiUrl };
  }

  console.log('Using default API URL:', defaultConfig.apiUrl);
  return defaultConfig;
};

interface MediaMetadata {
  file_name: string;
  content_type: string;
  user_id: string;
  created_at: string;
  expires_at: number;
  status: string;
}

interface MediaResponse {
  download_url: string;
  metadata: MediaMetadata;
}

const App: React.FC = () => {
  const [mediaId, setMediaId] = useState<string | null>(null);
  const [mediaData, setMediaData] = useState<MediaResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);

  useEffect(() => {
    // Load configuration when the application starts
    const loadConfig = async () => {
      try {
        const appConfig = await getConfig();
        setConfig(appConfig);
        console.log('App configuration loaded:', appConfig);

        // After loading configuration, check ID in URL
        const urlParams = new URLSearchParams(window.location.search);
        const id = urlParams.get('id');

        if (id) {
          setMediaId(id);
          fetchMediaData(id, appConfig.apiUrl);
        }
      } catch (err) {
        console.error('Error loading configuration:', err);
        setError('Failed to load application configuration');
      }
    };

    loadConfig();
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

      // Ensure the API base URL is properly formatted
      const normalizedApiUrl = apiBaseUrl.startsWith('http')
        ? apiBaseUrl
        : `${window.location.origin}${apiBaseUrl}`;

      console.log('Using normalized API URL:', normalizedApiUrl);
      const response = await fetch(`${normalizedApiUrl}/media/${encodedId}`);

      if (!response.ok) {
        throw new Error(`Error fetching media: ${response.statusText}`);
      }

      const data = await response.json();
      console.log('Media data received:', data);
      setMediaData(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error fetching media');
      console.error('Error fetching media:', err);
    } finally {
      setLoading(false);
    }
  };

  const renderMedia = () => {
    if (!mediaData) return null;

    const { download_url, metadata } = mediaData;
    const { content_type, file_name } = metadata;

    // Check if it's an image type
    const isImage = content_type.startsWith('image/');

    return (
      <div style={{ marginTop: '20px', width: '100%', maxWidth: '800px' }}>
        <h2>{file_name}</h2>

        {isImage && (
          <div style={{ margin: '20px 0' }}>
            <img
              src={download_url}
              alt={file_name}
              style={{ maxWidth: '100%', maxHeight: '500px' }}
            />
          </div>
        )}

        <div style={{ marginTop: '20px' }}>
          <a
            href={download_url}
            download={file_name}
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
            Download {file_name}
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

      {!mediaId && (
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
};

export default App; 