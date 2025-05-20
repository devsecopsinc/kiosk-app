import React, { useEffect, useState } from 'react';

// Define interfaces for component props and state
interface ThemeOptions {
  background_color?: string;
  text_color?: string;
  accent_color?: string;
  header_text?: string;
  logo_url?: string;
  custom_css?: string;
}

interface MediaData {
  mediaId: string;
  url: string;
  contentType: string;
  filename: string;
  createdAt: string;
  themeOptions?: ThemeOptions;
}

type Config = {
  apiBaseUrl: string;
  themesDirectory?: string;
  defaultTheme?: string;
  environment?: string;
  defaultLogoUrl?: string;
  headerText?: string;
};

// Main App component
function App() {
  // State for media data and loading state
  const [mediaData, setMediaData] = useState<MediaData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [themeOptions, setThemeOptions] = useState<ThemeOptions>({});
  const [config, setConfig] = useState<Config>({ apiBaseUrl: '/api/v1' });
  const [fallbackLogoUrl, setFallbackLogoUrl] = useState<string | null>(null);

  // Get configuration from different sources
  const getConfig = async (): Promise<Config> => {
    console.log('Initializing app config');

    // Default configuration
    const defaultConfig: Config = {
      apiBaseUrl: '/api/v1',
      themesDirectory: 'themes',
      defaultTheme: 'corporate',
      defaultLogoUrl: process.env.REACT_APP_DEFAULT_LOGO_URL || undefined,
      headerText: process.env.REACT_APP_HEADER_TEXT || undefined
    };

    try {
      const configResponse = await fetch('/config.json');
      if (configResponse.ok) {
        const config = await configResponse.json();
        console.log('Loaded config:', config);

        // Установить fallback URL логотипа, если есть в конфиге
        if (config.defaultLogoUrl) {
          setFallbackLogoUrl(config.defaultLogoUrl);
        } else if (defaultConfig.defaultLogoUrl) {
          setFallbackLogoUrl(defaultConfig.defaultLogoUrl);
        }

        setConfig(config);
        return { ...defaultConfig, ...config };
      }
    } catch (error) {
      console.warn('Failed to load config:', error);
    }

    // Return default config if loading fails
    return defaultConfig;
  };

  // Load theme from themes directory
  const loadTheme = async (themeName: string) => {
    if (!config.themesDirectory) return null;

    try {
      const themeResponse = await fetch(`/${config.themesDirectory}/${themeName}.json`);
      if (themeResponse.ok) {
        const themeData = await themeResponse.json();
        console.log(`Loaded theme ${themeName}:`, themeData);
        return themeData;
      }
    } catch (error) {
      console.warn(`Failed to load theme ${themeName}:`, error);
    }

    return null;
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

        // Check if theme name is in URL
        const themeName = urlParams.get('theme') || appConfig.defaultTheme;

        // Extract theme options from URL parameters (highest priority)
        const urlThemeOptions: ThemeOptions = {};
        if (urlParams.get('backgroundColor')) urlThemeOptions.background_color = urlParams.get('backgroundColor') || undefined;
        if (urlParams.get('textColor')) urlThemeOptions.text_color = urlParams.get('textColor') || undefined;
        if (urlParams.get('accentColor')) urlThemeOptions.accent_color = urlParams.get('accentColor') || undefined;
        if (urlParams.get('headerText')) urlThemeOptions.header_text = urlParams.get('headerText') || undefined;
        if (urlParams.get('logoUrl')) urlThemeOptions.logo_url = urlParams.get('logoUrl') || undefined;
        if (urlParams.get('customCss')) urlThemeOptions.custom_css = urlParams.get('customCss') || undefined;

        // If theme name is specified and no URL params override it, load theme from file
        if (themeName && Object.keys(urlThemeOptions).length === 0) {
          const themeData = await loadTheme(themeName);
          if (themeData) {
            setThemeOptions(themeData);
          }
        } else if (Object.keys(urlThemeOptions).length > 0) {
          // Apply URL theme options (highest priority)
          setThemeOptions(urlThemeOptions);
        }

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

      const headers: HeadersInit = {
        'Content-Type': 'application/json'
      };

      const response = await fetch(`${apiUrl}/media/${encodedId}`, {
        headers
      });

      if (!response.ok) {
        throw new Error(`HTTP error! Status: ${response.status}`);
      }

      const data = await response.json();
      // Transform API response to the format expected by the component
      const mediaDataFromApi: MediaData = {
        mediaId: id,
        url: data.download_url,
        contentType: data.metadata.content_type,
        filename: data.metadata.file_name,
        createdAt: data.metadata.created_at
      };

      // Apply theme from API if available and not overridden by URL params
      if (data.metadata.theme_options && Object.keys(themeOptions).length === 0) {
        setThemeOptions(data.metadata.theme_options);
        mediaDataFromApi.themeOptions = data.metadata.theme_options;
      } else if (Object.keys(themeOptions).length > 0) {
        // Keep URL params if they exist
        mediaDataFromApi.themeOptions = themeOptions;
      }

      setMediaData(mediaDataFromApi);
    } catch (err) {
      console.error('Error fetching media data:', err);
      setError('Failed to fetch');
    } finally {
      setLoading(false);
    }
  };

  // Apply theme styles to the page
  const getThemeStyles = (): React.CSSProperties => {
    const styles: React.CSSProperties = {
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      minHeight: '100vh',
      padding: '20px',
      textAlign: 'center'
    };

    if (themeOptions.background_color) {
      styles.backgroundColor = themeOptions.background_color;
    }

    if (themeOptions.text_color) {
      styles.color = themeOptions.text_color;
    }

    return styles;
  };

  // Get styles for buttons based on theme accent color
  const getButtonStyles = (): React.CSSProperties => {
    const styles: React.CSSProperties = {
      backgroundColor: themeOptions.accent_color || '#4CAF50',
      color: 'white',
      padding: '10px 20px',
      textDecoration: 'none',
      borderRadius: '4px',
      fontSize: '16px',
      display: 'inline-block'
    };

    return styles;
  };

  // Получение URL логотипа с проверкой валидности
  const getLogoUrl = (): string | null => {
    // Проверяем URL логотипа из темы
    if (themeOptions.logo_url) {
      // Проверяем, является ли URL действительным
      try {
        const url = new URL(themeOptions.logo_url);
        return themeOptions.logo_url;
      } catch (e) {
        console.warn('Invalid logo URL in theme options:', themeOptions.logo_url);
        // Если URL невалидный и начинается с /, считаем его относительным
        if (themeOptions.logo_url.startsWith('/')) {
          return `${window.location.origin}${themeOptions.logo_url}`;
        }
      }
    }

    // Возвращаем fallback URL или null, если он пустой
    return fallbackLogoUrl && fallbackLogoUrl !== "" ? fallbackLogoUrl : null;
  };

  // Получить текст заголовка
  const getHeaderText = (): string => {
    // Приоритет: 1. из URL, 2. из themeOptions, 3. из config.headerText, 4. дефолтный текст
    if (themeOptions.header_text) {
      return themeOptions.header_text;
    }

    if (config.headerText && config.headerText !== "") {
      return config.headerText;
    }

    return 'Media Sharing App';
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
            style={getButtonStyles()}
          >
            Download {filename}
          </a>
        </div>
      </div>
    );
  };

  // Apply custom CSS if provided
  useEffect(() => {
    if (themeOptions.custom_css) {
      const styleElement = document.createElement('style');
      styleElement.textContent = themeOptions.custom_css;
      document.head.appendChild(styleElement);

      return () => {
        document.head.removeChild(styleElement);
      };
    }
  }, [themeOptions.custom_css]);

  return (
    <div style={getThemeStyles()}>
      {getLogoUrl() && (
        <div style={{ marginBottom: '20px' }}>
          <img src={getLogoUrl() || ''} alt="Logo" style={{ maxHeight: '100px' }} />
        </div>
      )}

      <h1>{getHeaderText()}</h1>

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