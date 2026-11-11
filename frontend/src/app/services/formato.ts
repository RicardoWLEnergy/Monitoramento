/** "1 inversor" · "3 inversores" (para textos montados no código; nos templates use o pipe i18nPlural). */
export function plural(quantidade: number, singular: string, varios: string): string {
  return `${quantidade} ${quantidade === 1 ? singular : varios}`;
}
