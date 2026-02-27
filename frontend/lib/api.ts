import axios from 'axios';

// Use empty baseURL so that existing /api/stocks/... call paths work as-is.
// Next.js rewrites in next.config.js will intercept /api/* and proxy to backend:8000.
const getBaseUrl = () => {
    return process.env.NEXT_PUBLIC_API_URL || '';
};

const api = axios.create({
    baseURL: getBaseUrl(),
    timeout: 10000,
    headers: {
        'Content-Type': 'application/json',
    },
});

export default api;
