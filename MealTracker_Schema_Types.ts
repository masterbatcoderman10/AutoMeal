// ============================================
// ENUMS
// ============================================

export enum FoodSourceType {
    GENERIC = 'GENERIC',       // e.g. "apple", "boiled egg" — universal
    HOMEMADE = 'HOMEMADE',     // user-specific recipe
    RESTAURANT = 'RESTAURANT', // from a named restaurant
    PACKAGED = 'PACKAGED'      // branded product
}

export enum MealCategory {
    BREAKFAST = 'BREAKFAST',
    LUNCH = 'LUNCH',
    DINNER = 'DINNER',
    SNACK = 'SNACK',
    UNKNOWN = 'UNKNOWN'
}

export enum MealProcessingStatus {
    PENDING = 'PENDING',
    DETECTING = 'DETECTING',       // Step 1: is this food?
    SEGMENTING = 'SEGMENTING',     // Step 2: extract bounding boxes
    MATCHING = 'MATCHING',         // Step 3: vector search per segment
    REVIEWING = 'REVIEWING',       // Step 4: interview in progress
    COMPLETED = 'COMPLETED',
    NOT_FOOD = 'NOT_FOOD'          // Step 1 returned false
}

export enum IdentificationMethod {
    SIMILARITY = 'SIMILARITY',       // High-confidence vector match (>= threshold)
    LLM = 'LLM',                     // No good match — AI reasoned from image
    INTERVIEW = 'INTERVIEW',         // AI was uncertain; user clarified via Telegram
    USER_CORRECTED = 'USER_CORRECTED' // User overrode a previous identification
}

export enum InterviewStatus {
    PENDING = 'PENDING',
    IN_PROGRESS = 'IN_PROGRESS',
    COMPLETED = 'COMPLETED',
    ABANDONED = 'ABANDONED'
}

export enum InterviewSender {
    BOT = 'BOT',
    USER = 'USER'
}

/**
 * Structured keys for interview messages.
 * Each key represents a specific question/answer turn in the clarification flow.
 *
 * Flow order:
 *  INITIAL_QUESTION → FOOD_NAME → SOURCE_TYPE → (branch)
 *    ├── RESTAURANT_NAME (if RESTAURANT)
 *    ├── BRAND_NAME (if PACKAGED)
 *    └── (nothing extra if HOMEMADE / GENERIC)
 *  → PORTION_CONTEXT → CONFIRMATION
 */
export enum InterviewMessageKey {
    INITIAL_QUESTION = 'INITIAL_QUESTION',   // "Haven't seen this before — what is it?"
    FOOD_NAME = 'FOOD_NAME',                 // User provides the name
    SOURCE_TYPE = 'SOURCE_TYPE',             // Homemade / restaurant / packaged / generic
    RESTAURANT_NAME = 'RESTAURANT_NAME',     // If restaurant
    BRAND_NAME = 'BRAND_NAME',               // If packaged
    PORTION_CONTEXT = 'PORTION_CONTEXT',     // Is this a full portion, half, etc.?
    CONFIRMATION = 'CONFIRMATION',           // Bot summarises; user confirms or corrects
    CLARIFICATION = 'CLARIFICATION'          // Free-form back-and-forth if needed
}

// ============================================
// BASE INTERFACE
// ============================================

interface BaseEntity {
    id: string; // UUID
    created_at: Date;
}

// ============================================
// FOOD REFERENCE DATABASE
// ============================================

/**
 * FoodItems is the nutritional reference store.
 * One item can accumulate many visual representations in FoodVisuals,
 * which is what makes the system improve over time.
 *
 * Design note: standard_quantity + standard_unit define "1 portion".
 * All nutritional values are per that standard portion.
 * MealSegments store a quantity_multiplier (0.5, 1.0, 2.0, etc.)
 * to scale the nutrition at log time.
 */
export interface FoodItem extends BaseEntity {
    name: string;
    aliases: string[];          // Alternative names (e.g. ["chapati", "roti", "flatbread"])
    source_type: FoodSourceType;
    restaurant_name?: string;   // Populated when source_type = RESTAURANT
    brand_name?: string;        // Populated when source_type = PACKAGED

    // Nutritional data (per standard_quantity)
    calories_per_unit: number;
    carbs_per_unit: number;
    protein_per_unit: number;
    fat_per_unit: number;
    fiber_per_unit: number;
    glycemic_index?: number;

    // Portion reference
    standard_unit: string;      // e.g. "g", "ml", "piece", "cup"
    standard_quantity: number;  // e.g. 100 (grams), 1 (piece)

    // Learning metadata
    times_confirmed: number;    // Increments on every confirmed match or interview
    is_verified: boolean;       // True after at least one user confirmation

    // AI provenance — what the LLM said when creating this item
    llm_reasoning?: string;

    updated_at: Date;
}

/**
 * FoodVisuals stores one visual embedding per confirmed observation.
 * A single FoodItem (e.g. "daal chawal") can accumulate many FoodVisuals
 * across different plates, lighting conditions, and angles.
 *
 * The vector search in step 3 runs AGAINST this table.
 * High similarity (>= threshold) → auto-match the food item.
 * Every new confirmed segment adds a row here, growing the visual vocabulary.
 */
export interface FoodVisual extends BaseEntity {
    food_item_id: string;       // FK → FoodItem
    embedding: number[];        // vector(1024) — stored in pgvector
    source_segment_id: string;  // FK → MealSegment that produced this visual
}

// ============================================
// MEAL LOGGING
// ============================================

/**
 * MealLog represents one photo submission from the phone.
 * The processing_status field tracks where in the pipeline it sits.
 *
 * Aggregated nutritional totals are denormalised here from DiaryEntries
 * for fast daily/weekly summary queries.
 */
export interface MealLog extends BaseEntity {
    image_url: string;
    is_food: boolean;
    food_detection_confidence: number; // 0–1

    meal_category: MealCategory;       // AI-inferred from time of day
    processing_status: MealProcessingStatus;

    // Aggregated totals (populated once all segments are resolved)
    total_calories?: number;
    total_carbs?: number;
    total_protein?: number;
    total_fat?: number;
    total_fiber?: number;

    logged_at: Date; // The actual meal time (may differ from created_at)
}

/**
 * MealSegment is one bounding-box region detected within a MealLog image.
 *
 * Lifecycle:
 *  1. Created by segmentation AI with bounding_box + cropped_image_url
 *  2. Embedding generated; vector search run → sets matched_food_item_id
 *     and identification_method = SIMILARITY (if match found)
 *  3. If no match → LLM reasons → identification_method = LLM
 *     If LLM uncertain → needs_interview = true → InterviewSession created
 *  4. Once confirmed (any path) → DiaryEntry created + FoodVisual added
 *
 * quantity_multiplier is relative to FoodItem.standard_quantity.
 * e.g. if standard is 100g rice and the segment shows ~50g → multiplier = 0.5
 */
export interface MealSegment extends BaseEntity {
    meal_log_id: string;           // FK → MealLog

    // Visual region
    bounding_box: [number, number, number, number]; // [y0, x0, y1, x1] normalised 0–1
    cropped_image_url?: string;

    // Embedding for this segment (used to search FoodVisuals)
    embedding?: number[];          // vector(1024)

    // Resolution
    matched_food_item_id?: string; // FK → FoodItem (null until resolved)
    matched_visual_id?: string;    // FK → FoodVisual (which specific visual matched)
    identification_method?: IdentificationMethod;
    similarity_score?: number;     // 0–1; populated for SIMILARITY method

    // Quantity estimation
    quantity_multiplier?: number;  // Relative to FoodItem.standard_quantity
    estimated_quantity?: number;   // Derived: standard_quantity × multiplier
    unit?: string;                 // Inherited from matched FoodItem

    // AI's internal reasoning (surfaced to user in interview if needed)
    ai_reasoning?: string;

    // State flags
    needs_interview: boolean;
    interview_completed: boolean;
    user_confirmed: boolean;
}

// ============================================
// DIARY
// ============================================

/**
 * DiaryEntry is the clean, committed nutritional record.
 * Created once a MealSegment is fully resolved (matched or interviewed).
 * Values are pre-calculated at write time for fast query performance.
 *
 * Calculation: FoodItem.X_per_unit × quantity_multiplier
 */
export interface DiaryEntry extends BaseEntity {
    meal_log_id: string;        // FK → MealLog
    meal_segment_id?: string;   // FK → MealSegment (null if manually added)
    food_item_id: string;       // FK → FoodItem

    display_name: string;       // Denormalised from FoodItem.name for display
    quantity: number;
    unit: string;

    // Pre-calculated nutritional values
    calories: number;
    carbs: number;
    protein: number;
    fat: number;
    fiber: number;

    logged_at: Date;
}

// ============================================
// INTERVIEW (TELEGRAM BOT CLARIFICATION)
// ============================================

/**
 * InterviewSession is created when a MealSegment cannot be confidently resolved.
 * Triggers a Telegram bot conversation to collect:
 *  - What the food is
 *  - Whether it's homemade, from a restaurant, or packaged
 *  - Any additional context (restaurant name, brand, portion size)
 *
 * On completion, resulting_food_item_id is set and:
 *  1. FoodItem is created or updated
 *  2. MealSegment.interview_completed → true
 *  3. FoodVisual added with segment's embedding
 *  4. DiaryEntry created
 */
export interface InterviewSession extends BaseEntity {
    meal_segment_id: string;         // FK → MealSegment
    telegram_chat_id: string;        // Bot conversation target

    ai_initial_guess?: string;       // What the AI thought it was
    ai_initial_confidence?: number;  // How sure (0–1) the AI was before asking

    status: InterviewStatus;
    resulting_food_item_id?: string; // FK → FoodItem (set on COMPLETED)

    completed_at?: Date;
}

/**
 * InterviewMessage logs every turn in the Telegram conversation.
 * message_key provides structure so the backend can extract answers
 * programmatically rather than relying on free-text parsing alone.
 */
export interface InterviewMessage extends BaseEntity {
    session_id: string;             // FK → InterviewSession
    sender: InterviewSender;
    message_text: string;
    message_key: InterviewMessageKey;
    sent_at: Date;
}

// ============================================
// DATABASE SCHEMA TYPE
// ============================================

export interface DatabaseSchema {
    food_items: FoodItem[];
    food_visuals: FoodVisual[];
    meal_logs: MealLog[];
    meal_segments: MealSegment[];
    diary_entries: DiaryEntry[];
    interview_sessions: InterviewSession[];
    interview_messages: InterviewMessage[];
}

// ============================================
// PGVECTOR SETUP NOTES
// ============================================

/*
-- Enable extension
CREATE EXTENSION IF NOT EXISTS vector;

-- FoodVisuals embedding column
ALTER TABLE food_visuals ADD COLUMN embedding vector(1024);
CREATE INDEX ON food_visuals USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- MealSegments embedding column (transient, used for search)
ALTER TABLE meal_segments ADD COLUMN embedding vector(1024);

-- Similarity search query (Step 3 of pipeline)
SELECT
    fv.food_item_id,
    fi.name,
    fi.standard_quantity,
    fi.standard_unit,
    fi.calories_per_unit,
    fi.carbs_per_unit,
    fi.protein_per_unit,
    fi.fat_per_unit,
    fi.fiber_per_unit,
    1 - (fv.embedding <=> $1) AS similarity
FROM food_visuals fv
JOIN food_items fi ON fi.id = fv.food_item_id
WHERE 1 - (fv.embedding <=> $1) > 0.75  -- tunable threshold
ORDER BY fv.embedding <=> $1
LIMIT 3;

-- Similarity thresholds (recommended starting points):
--   >= 0.85 → auto-match, no review needed
--   0.65–0.84 → suggest to user, request confirmation
--   < 0.65 → trigger LLM reasoning; may escalate to interview
*/
