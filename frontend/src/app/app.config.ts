import { ApplicationConfig, LOCALE_ID, inject, provideAppInitializer, provideZoneChangeDetection } from '@angular/core';
import { registerLocaleData } from '@angular/common';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import localePt from '@angular/common/locales/pt';
import { provideRouter } from '@angular/router';

import { routes } from './app.routes';
import { AuthService } from './services/auth.service';
import { authInterceptor } from './services/auth.interceptor';

// Números no formato pt-BR (65,28 kWp · 1.288,4 kWh)
registerLocaleData(localePt, 'pt-BR');

export const appConfig: ApplicationConfig = {
  providers: [
    provideZoneChangeDetection({ eventCoalescing: true }),
    provideRouter(routes),
    provideHttpClient(withInterceptors([authInterceptor])),
    // Antes de abrir qualquer tela: se havia sessão salva, recupera o usuário
    provideAppInitializer(() => inject(AuthService).iniciar()),
    { provide: LOCALE_ID, useValue: 'pt-BR' },
  ],
};
