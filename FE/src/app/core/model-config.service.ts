import { Injectable, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { AuthService } from './auth.service';

export type ModelProvider = 'local' | 'groq';

export interface ModelConfig {
  defaultProvider: ModelProvider;
  localModel: string;
  groqModel: string;
  groqConfigured: boolean;
}

@Injectable({ providedIn: 'root' })
export class ModelConfigService {
  private readonly http = inject(HttpClient);
  private readonly auth = inject(AuthService);
  readonly config = signal<ModelConfig | null>(null);
  readonly provider = signal<ModelProvider>('local');

  async load(): Promise<ModelConfig> {
    const config = await firstValueFrom(this.http.get<ModelConfig>('/api/chat/config'));
    if (!this.config() || (this.provider() === 'groq' && !config.groqConfigured)) {
      this.provider.set(config.defaultProvider);
    }
    this.config.set(config);
    return config;
  }

  async save(
    body: Omit<ModelConfig, 'groqConfigured'> & {
      groqApiKey: string;
      removeGroqApiKey: boolean;
    },
  ): Promise<ModelConfig> {
    await this.auth.csrf();
    const config = await firstValueFrom(this.http.put<ModelConfig>('/api/chat/config', body));
    this.config.set(config);
    this.provider.set(config.defaultProvider);
    return config;
  }
}
