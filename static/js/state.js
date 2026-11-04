// Tiny shared app state (portfolios list used by several views). Refreshed by app.js.
import { api } from "./api.js";
export const state = { portfolios: [] };
export async function refreshPortfolios() {
  try { state.portfolios = await api.portfolios(); } catch { state.portfolios = []; }
  return state.portfolios;
}
