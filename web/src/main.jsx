import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

// StrictMode removed: it double-mounts effects in dev mode, causing
// WebSocket connect/disconnect/reconnect storms that flood the proxy.
createRoot(document.getElementById('root')).render(<App />)
