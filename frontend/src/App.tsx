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
      defaultTheme: 'default',
      defaultLogoUrl: undefined,
      headerText: undefined
    };

    try {
      console.log('Attempting to load config.json...');
      const configResponse = await fetch('/config.json');
      if (configResponse.ok) {
        const configData = await configResponse.json();
        console.log('✅ Loaded config.json successfully:', configData);

        // Explicit check for logo URL and header text in config
        if (configData.defaultLogoUrl) {
          console.log('Found logo URL in config:', configData.defaultLogoUrl);
          setFallbackLogoUrl(configData.defaultLogoUrl);
        }

        // Apply config to our state
        setConfig(configData);

        // Return merged config
        return { ...defaultConfig, ...configData };
      } else {
        console.warn('Failed to load config.json, status:', configResponse.status);
      }
    } catch (error) {
      console.error('Error loading config.json:', error);
    }

    // Return default config if loading fails
    console.warn('Using default configuration');
    return defaultConfig;
  };

  // Load theme based on configuration
  const loadTheme = async (themeValue: string): Promise<ThemeOptions | null> => {
    console.log('Loading theme, source value:', themeValue);

    // Проверяем, является ли themeValue URL-адресом
    let isUrl = false;
    try {
      new URL(themeValue);
      isUrl = true;
      console.log('Theme source is a URL');
    } catch (e) {
      console.log('Theme source is not a URL, using local theme');
    }

    try {
      let themeResponse;
      let themeUrl;

      if (isUrl) {
        // Загружаем тему по URL
        themeUrl = themeValue;
        console.log(`Loading theme from external URL: ${themeUrl}`);
      } else {
        // Загружаем локальную тему default.json
        themeUrl = '/themes/default.json';
        console.log(`Loading local theme: ${themeUrl}`);
      }

      themeResponse = await fetch(themeUrl);
      if (themeResponse.ok) {
        const themeData = await themeResponse.json();
        console.log('✅ Successfully loaded theme:', themeData);
        return themeData;
      } else {
        console.warn(`Failed to load theme from ${themeUrl}, status:`, themeResponse.status);
      }
    } catch (error) {
      console.error(`Failed to load theme: ${error}`);
    }

    console.warn('No theme loaded, returning null');
    return null;
  };

  useEffect(() => {
    const loadMediaFromUrl = async () => {
      setLoading(true);
      setError(null);

      try {
        console.log('=== Starting application initialization ===');
        const appConfig = await getConfig();
        console.log('App configuration loaded and merged with defaults:', appConfig);

        // Check if media ID is in URL
        const urlParams = new URLSearchParams(window.location.search);
        const id = urlParams.get('id');
        console.log('Media ID from URL:', id);

        // Extract theme options from URL parameters (highest priority)
        const urlThemeOptions: ThemeOptions = {};
        if (urlParams.get('backgroundColor')) urlThemeOptions.background_color = urlParams.get('backgroundColor') || undefined;
        if (urlParams.get('textColor')) urlThemeOptions.text_color = urlParams.get('textColor') || undefined;
        if (urlParams.get('accentColor')) urlThemeOptions.accent_color = urlParams.get('accentColor') || undefined;
        if (urlParams.get('headerText')) urlThemeOptions.header_text = urlParams.get('headerText') || undefined;
        if (urlParams.get('logoUrl')) urlThemeOptions.logo_url = urlParams.get('logoUrl') || undefined;
        if (urlParams.get('customCss')) urlThemeOptions.custom_css = urlParams.get('customCss') || undefined;

        // Применение тем в порядке приоритета:
        // 1. URL параметры
        // 2. Кастомизация из CloudFormation
        // 3. Базовая тема (default.json или по URL из DefaultTheme)

        console.log('Loading theme based on configuration...');

        // Загружаем тему на основе конфигурации
        const themeSource = appConfig.defaultTheme || 'default';
        console.log('Theme source (from config or default):', themeSource);
        const baseTheme = await loadTheme(themeSource);

        // CloudFormation параметры (из config.json)
        console.log('Applying CloudFormation parameters from config.json...');
        const configThemeOptions: ThemeOptions = {};

        if (appConfig.headerText) {
          console.log('Found headerText in config:', appConfig.headerText);
          configThemeOptions.header_text = appConfig.headerText;
        }

        if (appConfig.defaultLogoUrl) {
          console.log('Found defaultLogoUrl in config:', appConfig.defaultLogoUrl);
          configThemeOptions.logo_url = appConfig.defaultLogoUrl;
        }

        // Если есть параметры URL - используем их (высший приоритет)
        if (Object.keys(urlThemeOptions).length > 0) {
          console.log('URL parameters detected, applying with highest priority', urlThemeOptions);

          // Комбинируем базовую тему с URL параметрами
          const finalTheme = {
            ...(baseTheme || {}),
            ...configThemeOptions,
            ...urlThemeOptions
          };

          console.log('Final theme after applying URL parameters:', finalTheme);
          setThemeOptions(finalTheme);
        } else {
          // Иначе используем базовую тему с настройками из CloudFormation
          const finalTheme = {
            ...(baseTheme || {}),
            ...configThemeOptions
          };

          console.log('Final theme with CloudFormation parameters:', finalTheme);
          setThemeOptions(finalTheme);
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
    console.log('getLogoUrl called, themeOptions:', themeOptions);
    console.log('Fallback logo URL from config:', fallbackLogoUrl);

    // Проверяем URL логотипа из темы (высший приоритет)
    if (themeOptions.logo_url) {
      console.log('Found logo_url in theme options:', themeOptions.logo_url);
      try {
        // Проверяем валидность URL
        new URL(themeOptions.logo_url);
        console.log('Valid URL, returning theme logo URL');
        return themeOptions.logo_url;
      } catch (e) {
        console.warn('Invalid logo URL in theme options:', themeOptions.logo_url);
        // Если URL невалидный и начинается с /, считаем его относительным
        if (themeOptions.logo_url.startsWith('/')) {
          const fullUrl = `${window.location.origin}${themeOptions.logo_url}`;
          console.log('Converting relative URL to absolute:', fullUrl);
          return fullUrl;
        }
      }
    }

    // Возвращаем fallback URL или null, если он пустой
    if (fallbackLogoUrl && fallbackLogoUrl !== "") {
      console.log('Using fallback logo URL:', fallbackLogoUrl);
      return fallbackLogoUrl;
    }

    console.log('No logo URL found, returning null');
    return null;
  };

  // Получить текст заголовка
  const getHeaderText = (): string => {
    console.log('getHeaderText called, themeOptions:', themeOptions);
    console.log('Config headerText:', config.headerText);

    // Приоритет: из themeOptions, затем из конфига, потом дефолт
    if (themeOptions.header_text) {
      console.log('Using header text from theme options:', themeOptions.header_text);
      return themeOptions.header_text;
    }

    if (config.headerText && config.headerText !== "") {
      console.log('Using header text from config:', config.headerText);
      return config.headerText;
    }

    console.log('Using default header text');
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

  // Monitor themeOptions changes
  useEffect(() => {
    console.log('themeOptions changed:', themeOptions);

    // Recompute important values when theme changes
    if (Object.keys(themeOptions).length > 0) {
      const logo = getLogoUrl();
      const header = getHeaderText();
      console.log(`With current theme options, logo: ${logo}, header: ${header}`);
    }
  }, [themeOptions]);

  // Apply custom CSS if provided
  useEffect(() => {
    if (themeOptions.custom_css) {
      console.log('Applying custom CSS from theme');
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