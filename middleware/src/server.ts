import express from 'express';
import { config } from './config.js';
import { vmsRouter } from './routes/vms.js';
import { volumesRouter } from './routes/volumes.js';
import { organisationsRouter } from './routes/organisations.js';
import { facturationRouter } from './routes/facturation.js';

const app = express();
app.use(express.json());

app.get('/healthz', (_req, res) => res.json({ status: 'ok' }));

app.use('/vms', vmsRouter);
app.use('/volumes', volumesRouter);
app.use('/organisations', organisationsRouter);
app.use('/facturation', facturationRouter);

app.use((err: unknown, _req: express.Request, res: express.Response, _next: express.NextFunction) => {
  console.error(err);
  res.status(500).json({ error: err instanceof Error ? err.message : 'internal error' });
});

app.listen(config.port, () => {
  console.log(`middleware listening on :${config.port}`);
});
