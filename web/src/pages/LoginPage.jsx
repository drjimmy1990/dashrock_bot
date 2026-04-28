import { useState } from 'react';
import { useApp } from '../context/AppContext';

export default function LoginPage() {
  const { login } = useApp();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(username, password);
    } catch (err) {
      setError(err.message || 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={handleSubmit}>
        <h1>Dashrock</h1>
        <p>Sign in to your trading dashboard</p>
        {error && <div className="login-error">{error}</div>}
        <div className="input-group">
          <label htmlFor="login-user">Username</label>
          <input id="login-user" className="input-field" type="text" value={username}
            onChange={e => setUsername(e.target.value)} autoFocus placeholder="admin" />
        </div>
        <div className="input-group">
          <label htmlFor="login-pass">Password</label>
          <input id="login-pass" className="input-field" type="password" value={password}
            onChange={e => setPassword(e.target.value)} placeholder="••••••••" />
        </div>
        <button className="btn btn-primary" type="submit" disabled={loading} id="login-submit">
          {loading ? 'Signing in…' : 'Sign In'}
        </button>
      </form>
    </div>
  );
}
