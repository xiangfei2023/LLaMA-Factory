accelerate launch --config_file accelerate_config.yaml  src/train_bash.py \
    --stage sft \
    --model_name_or_path /home/mediatek/models/incite-7b-zh-base \
    --use_fast_tokenizer true \
    --do_train \
    --dataset instruct_tc_and_evol \
    --finetuning_type lora \
    --lora_target query_key_value \
    --prompt_template mr_chat \
    --output_dir ./outputs/incite-7b-zh-chat \
    --overwrite_cache \
    --per_device_train_batch_size 4 \
    --gradient_accumulation_steps 1 \
    --lr_scheduler_type cosine \
    --logging_steps 10 \
    --save_steps 1000 \
    --learning_rate 5e-5 \
    --num_train_epochs 3.0 \
    --plot_loss \
    --fp16