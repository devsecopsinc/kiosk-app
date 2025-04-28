import React from 'react';

const App: React.FC = () => {
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
      <p>Scan QR code or use direct link to access your media</p>
    </div>
  );
};

export default App; 