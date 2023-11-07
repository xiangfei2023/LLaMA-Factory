# Run(2.8GB)
```bash
CUDA_VISIBLE_DEVICES=0 python src/cli_demo.py \
    --model_name_or_path /home/houjinghp/data/llm/phi-1_5/ \
    --template default \
    --finetuning_type lora
```

# Train(more than 5 GB)
```bash
CUDA_VISIBLE_DEVICES=0 python src/train_bash.py \
    --stage sft \
    --model_name_or_path /home/houjinghp/data/llm/phi-1_5/ \
    --do_train \
    --dataset alpaca_gpt4_zh \
    --template default \
    --finetuning_type lora \
    --lora_target Wqkv \
    --lora_rank 2 \
    --output_dir path_to_sft_checkpoint \
    --overwrite_cache \
    --per_device_train_batch_size 1 \
    --gradient_accumulation_steps 4 \
    --lr_scheduler_type cosine \
    --logging_steps 10 \
    --save_steps 1000 \
    --learning_rate 5e-5 \
    --num_train_epochs 3.0 \
    --plot_loss \
    --fp16
```