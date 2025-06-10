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
  expiresAt?: string | number;
  themeOptions?: ThemeOptions;
}

type Config = {
  apiBaseUrl: string;
  themesDirectory?: string;
  customCSSURL?: string;
  environment?: string;
  defaultLogoUrl?: string;
  pageTitle?: string;
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
  const [customCSSLoaded, setCustomCSSLoaded] = useState(false);

  // Get configuration from environment variables
  const getConfig = async (): Promise<Config> => {
    console.log('Initializing app config from environment variables');

    // Default configuration - always use dark theme
    const defaultConfig: Config = {
      apiBaseUrl: '/api/v1',
      themesDirectory: 'themes',
      customCSSURL: '/themes/dark.css', // Default to dark theme
      defaultLogoUrl: undefined,
      pageTitle: undefined
    };

    // Read from process.env (from .env during build)
    const envConfig: Config = {
      apiBaseUrl: process.env.REACT_APP_API_BASE_URL || defaultConfig.apiBaseUrl,
      themesDirectory: process.env.REACT_APP_THEMES_DIRECTORY || defaultConfig.themesDirectory,
      customCSSURL: process.env.REACT_APP_CUSTOM_CSS_URL || defaultConfig.customCSSURL,
      environment: process.env.REACT_APP_ENVIRONMENT,
      defaultLogoUrl: process.env.REACT_APP_DEFAULT_LOGO_URL || undefined,
      pageTitle: process.env.REACT_APP_PAGE_TITLE || undefined
    };

    console.log('Configuration from environment:', envConfig);

    // Set fallback logo URL if available
    if (envConfig.defaultLogoUrl) {
      console.log('Found logo URL in env config:', envConfig.defaultLogoUrl);
      setFallbackLogoUrl(envConfig.defaultLogoUrl);
    }

    // Apply config to our state
    const mergedConfig = { ...defaultConfig, ...envConfig };
    setConfig(mergedConfig);

    return mergedConfig;
  };

  // Load CSS based on configuration
  const loadCustomCSS = async (cssURLValue: string): Promise<boolean> => {
    console.log('Loading custom CSS, source value:', cssURLValue);

    try {
      let cssUrl = 'themes/dark.css'; // Default to dark theme

      // Check if cssURLValue is a URL
      let isUrl = false;
      try {
        if (cssURLValue) {
          new URL(cssURLValue);
          isUrl = true;
          console.log('CSS source is a URL');
          cssUrl = cssURLValue; // Use external URL if valid
        }
      } catch (e) {
        // If it's not a URL but has a value different from default, use it as a relative path
        if (cssURLValue && cssURLValue !== 'themes/dark.css') {
          cssUrl = cssURLValue;
          console.log('CSS source is a custom relative path:', cssUrl);
        } else {
          console.log('Using default dark theme CSS');
        }
      }

      // Create a new link element
      const linkElement = document.createElement('link');
      linkElement.rel = 'stylesheet';
      linkElement.href = cssUrl;
      linkElement.id = 'custom-theme-css';

      // Remove any existing custom CSS link
      const existingLink = document.getElementById('custom-theme-css');
      if (existingLink && existingLink.parentNode) {
        existingLink.parentNode.removeChild(existingLink);
      }

      // Add the new link to the head
      document.head.appendChild(linkElement);

      // Set up load and error event handlers
      return new Promise((resolve) => {
        linkElement.onload = () => {
          console.log('✅ Successfully loaded CSS from:', cssUrl);
          resolve(true);
        };

        linkElement.onerror = () => {
          console.warn(`Failed to load CSS from ${cssUrl}, falling back to default dark theme`);
          // If custom CSS fails, fall back to the default dark theme
          if (cssUrl !== 'themes/dark.css') {
            const fallbackLink = document.createElement('link');
            fallbackLink.rel = 'stylesheet';
            fallbackLink.href = 'themes/dark.css';
            fallbackLink.id = 'custom-theme-css';
            document.head.appendChild(fallbackLink);
          }
          resolve(false);
        };
      });
    } catch (error) {
      console.error(`Failed to load CSS: ${error}`);
      return false;
    }
  };

  useEffect(() => {
    const loadMediaFromUrl = async () => {
      try {
        console.log('=== Starting application initialization ===');
        const appConfig = await getConfig();
        console.log('App configuration loaded:', appConfig);

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

        // Priority for styling:
        // 1. Load the CSS file (external URL or dark.css by default)
        // 2. Apply URL parameters if present
        // 3. Apply environment variables from config

        console.log('Loading CSS based on configuration...');

        // Always load dark theme by default, unless customCSSURL is specified
        const cssSource = appConfig.customCSSURL || '/themes/dark.css';
        console.log('CSS source (from config or default):', cssSource);
        const cssLoaded = await loadCustomCSS(cssSource);
        setCustomCSSLoaded(cssLoaded);

        // Environment variables (from config)
        console.log('Applying environment variables from config...');
        const configThemeOptions: ThemeOptions = {};

        if (appConfig.pageTitle) {
          console.log('Found pageTitle in config:', appConfig.pageTitle);
          configThemeOptions.header_text = appConfig.pageTitle;
          // Also set page title directly
          document.title = appConfig.pageTitle;
        }

        if (appConfig.defaultLogoUrl) {
          console.log('Found defaultLogoUrl in config:', appConfig.defaultLogoUrl);
          configThemeOptions.logo_url = appConfig.defaultLogoUrl;
        }

        console.log('Config theme options:', configThemeOptions);

        // If there are URL parameters, use them (highest priority)
        if (Object.keys(urlThemeOptions).length > 0) {
          console.log('URL parameters detected, applying with highest priority', urlThemeOptions);

          // Combine theme options with URL parameters
          const finalTheme = {
            ...configThemeOptions,
            ...urlThemeOptions
          };

          console.log('Final theme after applying URL parameters:', finalTheme);
          setThemeOptions(finalTheme);

          // Update page title if headerText is provided in URL
          if (urlThemeOptions.header_text) {
            document.title = urlThemeOptions.header_text;
          } else if (configThemeOptions.header_text) {
            document.title = configThemeOptions.header_text;
          }
        } else {
          // Otherwise just use environment settings
          console.log('Final theme with environment variables:', configThemeOptions);
          setThemeOptions(configThemeOptions);

          // Update page title if headerText is provided in config
          if (configThemeOptions.header_text) {
            document.title = configThemeOptions.header_text;
          }
        }

        // Set loading false if no media ID provided
        if (!id) {
          setLoading(false);
          setError('No media ID provided');
        } else {
          // Fetch media data
          await fetchMediaData(id, appConfig.apiBaseUrl);
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
        throw new Error(`API request failed with status: ${response.status}`);
      }

      const data = await response.json();
      console.log('Media data received:', data);

      // Ensure we have all required fields in media data
      const mediaDataFormatted: MediaData = {
        mediaId: data.mediaId || id,
        url: data.download_url || data.url || '',
        contentType: data.contentType || data.metadata?.content_type || 'application/octet-stream',
        filename: data.filename || data.metadata?.file_name || 'download',
        createdAt: data.createdAt || data.metadata?.created_at || new Date().toISOString(),
        expiresAt: data.expiresAt || data.metadata?.expires_at || undefined,
        themeOptions: data.themeOptions || {}
      };

      setMediaData(mediaDataFormatted);

      // Update page title from media data if available
      if (data.themeOptions?.header_text) {
        document.title = data.themeOptions.header_text;
      }

      setLoading(false);
    } catch (err) {
      console.error('Error fetching media:', err);
      setLoading(false);
      setError('Failed to load media. The link may be expired or invalid.');
    }
  };

  const getLogoUrl = (): string | null => {
    console.log('Getting logo URL. mediaData:', mediaData?.themeOptions, 'themeOptions:', themeOptions, 'fallbackLogoUrl:', fallbackLogoUrl);

    // If media data includes a logo_url, use that
    if (mediaData?.themeOptions?.logo_url) {
      console.log('Using logo URL from media data:', mediaData.themeOptions.logo_url);
      return mediaData.themeOptions.logo_url;
    }

    // Otherwise use theme options from URL/env
    if (themeOptions.logo_url) {
      console.log('Using logo URL from theme options:', themeOptions.logo_url);
      return themeOptions.logo_url;
    }

    // Fallback to default logo if configured
    console.log('Using fallback logo URL:', fallbackLogoUrl);
    return fallbackLogoUrl;
  };

  const getHeaderText = (): string => {
    console.log('Getting header text. mediaData:', mediaData?.themeOptions, 'themeOptions:', themeOptions);

    // If media data includes a header_text, use that
    if (mediaData?.themeOptions?.header_text) {
      console.log('Using header text from media data:', mediaData.themeOptions.header_text);
      return mediaData.themeOptions.header_text;
    }

    // Otherwise use theme options from URL/env
    if (themeOptions.header_text) {
      console.log('Using header text from theme options:', themeOptions.header_text);
      return themeOptions.header_text;
    }

    // Default
    console.log('Using default header text: "Media Sharing"');
    return "Media Sharing";
  };

  const formatDate = (dateString: string | number | undefined): string => {
    if (!dateString) return 'N/A';

    try {
      // If it's a number (Unix timestamp in seconds), convert to milliseconds
      const date = typeof dateString === 'number'
        ? new Date(dateString * 1000)
        : new Date(dateString);

      return new Intl.DateTimeFormat('en-US', {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      }).format(date);
    } catch (e) {
      return String(dateString);
    }
  };

  const renderMedia = () => {
    if (!mediaData) return null;

    // Ensure all required properties exist
    const contentType = mediaData.contentType || 'application/octet-stream';
    const url = mediaData.url || '';
    const filename = mediaData.filename || 'file';

    if (contentType.startsWith('image/')) {
      return <img id="media-image" src={url} alt={filename} />;
    } else if (contentType.startsWith('video/')) {
      return (
        <video id="media-video" controls>
          <source src={url} type={contentType} />
          Your browser does not support the video tag.
        </video>
      );
    } else if (contentType.startsWith('audio/')) {
      return (
        <audio id="media-audio" controls>
          <source src={url} type={contentType} />
          Your browser does not support the audio tag.
        </audio>
      );
    } else {
      // For other files (documents, etc.) show a download link
      return (
        <div id="generic-file-container">
          <p id="generic-file-message">This file type can't be previewed directly.</p>
          <p id="generic-file-name">{filename}</p>
        </div>
      );
    }
  };

  if (loading) {
    return (
      <div id="app-container">
        <div id="loading-container">
          <div id="loading-indicator"></div>
          <p id="loading-text">Loading...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div id="app-container">
        <div id="error-container">
          <h2 id="error-title">Error</h2>
          <p id="error-message">{error}</p>
        </div>
      </div>
    );
  }

  const logoUrl = getLogoUrl();
  const headerText = getHeaderText();

  return (
    <div id="app-container">
      <header id="header">
        {logoUrl && (
          <img id="logo" src={logoUrl} alt="Logo" />
        )}
        <h1 id="header-text">{headerText}</h1>
      </header>

      {mediaData && (
        <div id="media-container">
          <div id="media-content">
            {renderMedia()}
          </div>

          <div id="file-info">
            <div id="file-name">{mediaData.filename}</div>
            <div id="file-type">{mediaData.contentType}</div>
            <div id="created-date">
              Created: {formatDate(mediaData.createdAt)}
            </div>
            {mediaData.expiresAt && (
              <div id="expires-date">
                Expires: {formatDate(mediaData.expiresAt)}
              </div>
            )}
          </div>

          <div id="download-container">
          <a
            id="download-button"
            href={mediaData.url}
            download={mediaData.filename}
            target="_blank"
            rel="noopener noreferrer"
          >
            Download
          </a>
          </div>
        </div>
      )}
    </div>
  );
}

export default App; 