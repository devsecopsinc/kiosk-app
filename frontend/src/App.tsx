import React, { useEffect, useState } from 'react';

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

  useEffect(() => {
    // Get media ID from URL query parameter
    const urlParams = new URLSearchParams(window.location.search);
    const id = urlParams.get('id');

    if (id) {
      setMediaId(id);
      fetchMediaData(id);
    }
  }, []);

  const fetchMediaData = async (id: string) => {
    setLoading(true);
    setError(null);

    try {
      // Replace with your actual API endpoint
      const apiUrl = process.env.REACT_APP_API_URL || '/api/v1';
      const response = await fetch(`${apiUrl}/media/${id}`);

      if (!response.ok) {
        throw new Error(`Error fetching media: ${response.statusText}`);
      }

      const data = await response.json();
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