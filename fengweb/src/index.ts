import { createServer } from './server';

const PORT = parseInt(process.env.PORT || '3000', 10);
createServer(PORT);
