import { Component, OnChanges, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Fabricante, Usina } from '../../core/usinas.mock';
import { ConfigUsina, UsinasService } from '../../core/usinas.service';

interface Formulario {
  nome: string; cliente: string; cidade: string; potenciaKwp: number;
  fabricante: Fabricante; esperadoMesKwh: number; config: ConfigUsina;
}

/** Aba "Configurações" do detalhe: cadastro, integração e limites de alerta. */
@Component({
  selector: 'app-usina-config',
  imports: [FormsModule],
  templateUrl: './usina-config.component.html',
  styleUrl: './usina-config.component.css',
})
export class UsinaConfigComponent implements OnChanges {
  private readonly servico = inject(UsinasService);

  readonly usina = input.required<Usina>();

  readonly fabricantes: Fabricante[] = ['WEG', 'FoxESS', 'Huawei'];
  form!: Formulario;
  readonly salvando = signal(false);
  readonly salvo = signal(false);

  /** Recarrega o formulário quando a usina (input) muda. */
  ngOnChanges(): void {
    this.carregar(this.usina());
  }

  descartar(): void {
    this.carregar(this.usina());
    this.salvo.set(false);
  }

  private carregar(u: Usina): void {
    this.form = {
      nome: u.nome, cliente: u.cliente, cidade: u.cidade, potenciaKwp: u.potenciaKwp,
      fabricante: u.fabricante, esperadoMesKwh: u.esperadoMesKwh,
      config: { ...this.servico.config(u.id)! },
    };
  }

  async salvar(): Promise<void> {
    this.salvando.set(true);
    const { config, ...dados } = this.form;
    await this.servico.salvar(this.usina().id, dados, config);
    this.salvando.set(false);
    this.salvo.set(true);
  }
}
