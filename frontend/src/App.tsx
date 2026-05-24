import React, { useState, useEffect } from 'react';
import './App.css';
import Dashboard from './components/Dashboard';
import EnhancedDashboard from './components/EnhancedDashboard';

function App() {
  const [useEnhanced, setUseEnhanced] = useState(true);

  return (
    <div className="app">
      {useEnhanced ? (
        <EnhancedDashboard />
      ) : (
        <Dashboard />
      )}
    </div>
  );
}

export default App;
