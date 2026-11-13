import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { errorMessage } from '../../core/api.service';
import { ModelConfig, ModelConfigService, ModelProvider } from '../../core/model-config.service';

@Component({
  selector: 'app-model-config',
  imports: [FormsModule, RouterLink],
  templateUrl: './model-config.component.html',
  styleUrl: './model-config.component.css',
})
export class ModelConfigComponent implements OnInit {
  readonly models = inject(ModelConfigService);
  readonly loading = signal(true);
  readonly saving = signal(false);
  readonly error = signal('');
  readonly notice = signal('');
  defaultProvider: ModelProvider = 'local';
  localModel = '';
  groqModel = '';
  groqApiKey = '';
  removeGroqApiKey = false;

  get retiredGroqModel(): boolean {
    return ['llama-3.3-70b-versatile', 'llama-3.1-8b-instant'].includes(this.groqModel.trim());
  }

  ngOnInit(): void {
    void this.load();
  }

  async load(): Promise<void> {
    this.loading.set(true);
    this.error.set('');
    try {
      this.populate(await this.models.load());
    } catch (error) {
      this.error.set(errorMessage(error));
    } finally {
      this.loading.set(false);
    }
  }

  async save(): Promise<void> {
    if (this.loading() || this.saving()) return;
    this.saving.set(true);
    this.error.set('');
    this.notice.set('');
    try {
      this.populate(
        await this.models.save({
          defaultProvider: this.defaultProvider,
          localModel: this.localModel.trim(),
          groqModel: this.groqModel.trim(),
          groqApiKey: this.groqApiKey.trim(),
          removeGroqApiKey: this.removeGroqApiKey,
        }),
      );
      this.notice.set('Đã lưu. Bạn có thể chọn Local hoặc Groq trong ô chat.');
    } catch (error) {
      this.error.set(errorMessage(error));
    } finally {
      this.saving.set(false);
    }
  }

  private populate(config: ModelConfig): void {
    this.defaultProvider = config.defaultProvider;
    this.localModel = config.localModel;
    this.groqModel = config.groqModel;
    this.groqApiKey = '';
    this.removeGroqApiKey = false;
  }
}
