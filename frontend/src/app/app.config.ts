import { ApplicationConfig, LOCALE_ID, inject, provideAppInitializer, provideZoneChangeDetection } from '@angular/core';
import { registerLocaleData } from '@angular/common';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import localePt from '@angular/common/locales/pt';
import { provideRouter, withNavigationErrorHandler } from '@angular/router';

import { routes } from './app.routes';
import { AuthService } from './services/auth.service';
import { authInterceptor } from './services/auth.interceptor';
import { manutencaoInterceptor } from './services/manutencao.interceptor';

// Números no formato pt-BR (65,28 kWp · 1.288,4 kWh)
registerLocaleData(localePt, 'pt-BR');

/**
 * Depois de uma atualização, quem estava com o sistema aberto ainda tem a versão antiga, que pede
 * arquivos de tela que não existem mais ("Failed to fetch dynamically imported module").
 * Nesse caso recarrega a página uma vez (no máximo a cada 30 s, para nunca ficar em laço).
 */
function recarregarSeAVersaoMudou(erro: { error?: unknown }): void {
  const texto = String((erro?.error as Error)?.message ?? erro?.error ?? '');
  if (!/dynamically imported module|Loading chunk|Importing a module script failed/i.test(texto)) return;
  try {
    const ultima = Number(sessionStorage.getItem('wl-recarga-versao') || 0);
    if (Date.now() - ultima < 30_000) return;
    sessionStorage.setItem('wl-recarga-versao', String(Date.now()));
  } catch { /* sem sessionStorage: recarrega mesmo assim */ }
  location.reload();
}

export const appConfig: ApplicationConfig = {
  providers: [
    provideZoneChangeDetection({ eventCoalescing: true }),
    provideRouter(routes, withNavigationErrorHandler(recarregarSeAVersaoMudou)),
    provideHttpClient(withInterceptors([manutencaoInterceptor, authInterceptor])),
    // Antes de abrir qualquer tela: se havia sessão salva, recupera o usuário
    provideAppInitializer(() => inject(AuthService).iniciar()),
    { provide: LOCALE_ID, useValue: 'pt-BR' },
  ],
};
