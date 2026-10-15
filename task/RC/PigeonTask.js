/*******************
 * Pigeontask Test *
 *******************/

/*
 * RC (reward change) pigeon-tracking decision task (PsychoJS).
 *
 * Derived from task/MXSC/PigeonTask.js. That file was compiled by the PsychoPy Builder, then
 * hand-edited; the Builder file is obsolete, so this JS is the source of truth and is edited
 * directly (never regenerated from Builder). Most of it (component construction, per-frame
 * setPos/setSize/setAutoDraw calls, loop/scheduler wiring) is Builder-style boilerplate; the
 * task's behavior lives in the "Run 'Begin/Each Frame/End Routine' code from <component>"
 * blocks, documented in place below.
 *
 * Task idea: a pigeon ("Petey") starts at the center of the screen and takes a biased random
 * walk (see move_pigeon_function) that drifts toward a left or right seed pile. On each step
 * the participant may press Left/Right to commit to a choice ("which pile will Petey end up
 * at"); the trial ends on a response, or after STEPS_MAX_PER_TRIAL steps with no response
 * (timeout: no choice, no coins). Difficulty (step mean/SD) is the same in every block; only
 * the reward changes.
 *
 * Session flow (see the flowScheduler wiring below):
 *   consent -> experiment_setup (global config) -> general_instructions_loop -> simple_demo
 *   (practice walks, no response required) -> status_instruction_loop (explains the coins/
 *   steps status bars and step charges) -> experiment_loop (the four task blocks) ->
 *   final_message -> show_final_message.
 *
 * Each row of PigeonTaskConditions.xlsx is one block and drives start_task via tc_* columns.
 * block_type names are inherited from MXSC, where low/high meant SNR; here they mean REWARD:
 *   - "fixed_low"  : +1 / -1 coins (correct / error) on every trial (cactus icon).
 *   - "fixed_high" : +3 / -3 coins on every trial (tree icon).
 *   - "change_low" : rising reward. Each trial starts at the low reward (tc_coins_gained_per_
 *     correct / tc_coins_lost_per_error) and switches to the high reward (tc_coins_gained_post /
 *     tc_coins_lost_post) once steps_in_trial reaches switch_time; a countdown bar shows the
 *     steps left until the switch.
 *   - "change_high": falling reward, the reverse.
 * A response is scored with the coin values in force on the step it was made, so a response
 * made while position index >= switch_time is shown earns the post-switch values.
 * switch_time is the participant's median RT (in steps) over BOTH fixed blocks pooled, each
 * block's first RT_WARMUP_TRIALS_TO_DISCARD trials dropped, and is the same in both change
 * blocks; the RT-extremity screen (check_rt_extremity) runs once, on the same pooled RTs,
 * when the second fixed block ends.
 *
 * Block order: the two fixed blocks run first, in random order, then the two change blocks,
 * in random order (experiment_loopLoopBegin); the order is saved as block_order.
 *
 * Every block's objective is a fixed step budget (steps_max). Steps used = Petey's steps +
 * steps_taken_to_start_trial per trial + steps_lost_per_error per error. An end-of-block
 * bonus is earned if coins_count reaches that block's coins_max target (set_block_end_string).
 *
 * Every condition-loop in this file imports one row of its xlsx file per iteration via
 * importConditions(), which dumps that row's columns into globals named by the sheet's own
 * prefix convention: gic_* (general instructions), sdc_* (simple demo), sic_* (status
 * instructions), tc_* (task/block), ic_* (per-block instructions, chosen by instructions_type =
 * block_type.split("_")[0] -> Pigeon_<fixed|change>_InstructionsConditions.xlsx).
 *
 * trial_loop and move_loop are both declared with a large fixed nReps (10000 / 1000) and
 * are not meant to run that many times in practice -- they are open-ended counters that the
 * task code itself terminates early by setting trial_loop.finished / move_loop.finished
 * once a block's step budget is exhausted (trial_loop) or a trial ends (move_loop).
 * Each move_loop iteration is one call to task_run, i.e. one animation step of Petey's walk.
 */

import { core, data, sound, util, visual, hardware } from './lib/psychojs-2023.1.2.js';
const { PsychoJS } = core;
const { TrialHandler, MultiStairHandler } = data;
const { Scheduler } = util;
//some handy aliases as in the psychopy scripts;
const { abs, sin, cos, PI: pi, sqrt } = Math;
const { round } = util;


// store info about the experiment session:
let expName = 'PigeonTask';  // from the Builder filename that created this script
let expInfo = {
    'participant': '',
    'session': '001',
};

// Start code blocks for 'Before Experiment'
// Run 'Before Experiment' code from es_code_setup

// Reward-switch timing is the median RT (in steps) of the two fixed blocks pooled, rounded
// to an integer step count. `arr` is a list of per-trial RTs measured in pigeon-walk steps
// (each entry = pigeon_steps.length from that trial), not seconds. Falls back to 10 steps if
// no RTs were collected, so the change blocks still have a usable switch_time.
function calculate_median(arr) {
    if (arr.length === 0) return 10;

    arr.sort((a, b) => a - b);
    let n = arr.length;
    let mid = Math.floor(n / 2);

    return Math.round(n % 2 === 0 ? (arr[mid - 1] + arr[mid]) / 2 : arr[mid]);
}

// Drops the first RT_WARMUP_TRIALS_TO_DISCARD entries (if enough trials exist) before
// computing changepoint timing / RT-extremity stats, so early "getting used to the task"
// RTs at the start of a block don't skew either.
function trim_warmup_trials(arr) {
    return arr.length > RT_WARMUP_TRIALS_TO_DISCARD ? arr.slice(RT_WARMUP_TRIALS_TO_DISCARD) : arr;
}

// Flags participants whose RT distribution on the fixed blocks is too extreme to be
// usable: guessing on (almost) every trial (median RT below RT_TOO_FAST_STEPS) or mostly
// not responding within the trial (median RT above RT_TOO_SLOW_STEPS, or too large a
// fraction of trials timing out at STEPS_MAX_PER_TRIAL). `rts` is the (warmup-trimmed) list
// of responded-trial RTs used for the median check; `timeout_fraction` is computed
// separately by the caller from the fixed blocks' timeout counts (see task_runRoutineEnd)
// rather than derived from `rts`, since `rts` only ever contains trials that got a response
// -- a real timeout never appears in it, so a fraction computed from `rts` alone could never
// detect "frequently not responding" at all. Returns null if the block's RTs look usable,
// otherwise a short reason string used to end the session early (see fm_code_setup).
function check_rt_extremity(rts, timeout_fraction) {
    if (rts.length === 0) return null;
    let sorted = rts.slice().sort((a, b) => a - b);
    let n = sorted.length;
    let mid = Math.floor(n / 2);
    let median_rt = n % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
    if (median_rt < RT_TOO_FAST_STEPS) return "too_fast";
    if (median_rt > RT_TOO_SLOW_STEPS || timeout_fraction > RT_TIMEOUT_FRACTION_MAX) return "too_slow";
    return null;
}
// init psychoJS:
const psychoJS = new PsychoJS({
  debug: true
});

// open window:
psychoJS.openWindow({
  fullscr: true,
  color: new util.Color([0,0,0]),
  units: 'height',
  waitBlanking: true
});

// Guard against the layout breaking under a narrow (portrait-ish) browser window. With
// units: 'height', PsychoJS scales every stim from Math.min(window.width, window.height)
// (see WindowMixin._getLengthPix in the PsychoJS source) rather than from height alone, so
// once the window becomes narrower than about 1.6x its own height, elements positioned near
// the edges of this task's (16:9-oriented) layout -- status-bar labels, seed piles -- land
// outside the visible canvas and get clipped, and everything on screen rescales/shifts the
// moment width crosses below height. Rather than reflow the whole layout for arbitrary
// aspect ratios, block the view with a "please widen your window" overlay whenever the
// window is too narrow, and reveal the (correctly laid out, since the ratio is safe again)
// task underneath once it's wide enough.
const MIN_WINDOW_ASPECT_RATIO = 1.6;
const aspectRatioOverlay = document.createElement('div');
aspectRatioOverlay.id = 'aspect-ratio-overlay';
aspectRatioOverlay.style.cssText = 'display:none;position:fixed;inset:0;z-index:9999;'
  + 'background:black;color:white;align-items:center;justify-content:center;'
  + 'text-align:center;font-family:sans-serif;font-size:1.5em;padding:2em;box-sizing:border-box;';
aspectRatioOverlay.textContent = 'Please widen your browser window (or rotate your device to '
  + 'landscape) to continue. This task needs a window that is significantly wider than it is tall.';
document.body.appendChild(aspectRatioOverlay);
function _updateAspectRatioOverlay() {
  const tooNarrow = (window.innerWidth / window.innerHeight) < MIN_WINDOW_ASPECT_RATIO;
  aspectRatioOverlay.style.display = tooNarrow ? 'flex' : 'none';
}
window.addEventListener('resize', _updateAspectRatioOverlay);
window.addEventListener('orientationchange', _updateAspectRatioOverlay);
// Swallow keyboard input while the overlay covers a too-narrow window, so a participant
// can't blindly commit a response (e.g. Left/Right) they can't see. Registered on the
// capture phase so it runs, and can stop propagation, before PsychoJS's own key listeners.
document.addEventListener('keydown', function(event) {
  if (aspectRatioOverlay.style.display === 'flex') {
    event.stopImmediatePropagation();
  }
}, true);
_updateAspectRatioOverlay();

// schedule the experiment:
psychoJS.schedule(psychoJS.gui.DlgFromDict({
  dictionary: expInfo,
  title: expName
}));

const flowScheduler = new Scheduler(psychoJS);
const dialogCancelScheduler = new Scheduler(psychoJS);
psychoJS.scheduleCondition(function() { return (psychoJS.gui.dialogComponent.button === 'OK'); }, flowScheduler, dialogCancelScheduler);

// flowScheduler gets run if the participants presses OK.
// This is the top-level session flow described in the file header: consent -> setup ->
// general instructions -> practice demo -> status-bar instructions -> the real task blocks
// (experiment_loop) -> final message(s). Each "Routine" trio (Begin/EachFrame/End) below runs
// once per screen; each "Loop" wraps a TrialHandler that repeats a sub-sequence of routines
// once per row of an xlsx conditions file (or, for trial_loop/move_loop, once per trial/step).
flowScheduler.add(updateInfo); // add timeStamp
flowScheduler.add(experimentInit);
flowScheduler.add(consentRoutineBegin());
flowScheduler.add(consentRoutineEachFrame());
flowScheduler.add(consentRoutineEnd());
flowScheduler.add(experiment_setupRoutineBegin());
flowScheduler.add(experiment_setupRoutineEachFrame());
flowScheduler.add(experiment_setupRoutineEnd());
const general_instructions_loopLoopScheduler = new Scheduler(psychoJS);
flowScheduler.add(general_instructions_loopLoopBegin(general_instructions_loopLoopScheduler));
flowScheduler.add(general_instructions_loopLoopScheduler);
flowScheduler.add(general_instructions_loopLoopEnd);
const simple_demo_block_loopLoopScheduler = new Scheduler(psychoJS);
flowScheduler.add(simple_demo_block_loopLoopBegin(simple_demo_block_loopLoopScheduler));
flowScheduler.add(simple_demo_block_loopLoopScheduler);
flowScheduler.add(simple_demo_block_loopLoopEnd);
const status_instruction_loopLoopScheduler = new Scheduler(psychoJS);
flowScheduler.add(status_instruction_loopLoopBegin(status_instruction_loopLoopScheduler));
flowScheduler.add(status_instruction_loopLoopScheduler);
flowScheduler.add(status_instruction_loopLoopEnd);
const experiment_loopLoopScheduler = new Scheduler(psychoJS);
flowScheduler.add(experiment_loopLoopBegin(experiment_loopLoopScheduler));
flowScheduler.add(experiment_loopLoopScheduler);
flowScheduler.add(experiment_loopLoopEnd);
flowScheduler.add(final_messageRoutineBegin());
flowScheduler.add(final_messageRoutineEachFrame());
flowScheduler.add(final_messageRoutineEnd());
flowScheduler.add(show_final_messageRoutineBegin());
flowScheduler.add(show_final_messageRoutineEachFrame());
flowScheduler.add(show_final_messageRoutineEnd());
flowScheduler.add(quitPsychoJS, '', true);

// quit if user presses Cancel in dialog box:
dialogCancelScheduler.add(quitPsychoJS, '', false);

psychoJS.start({
  expName: expName,
  expInfo: expInfo,
  resources: [
    // resources:
    {'name': 'Resources/PigeonGeneralInstructionsConditions.xlsx', 'path': 'Resources/PigeonGeneralInstructionsConditions.xlsx'},
    {'name': 'Resources/PigeonSimpleDemoConditions.xlsx', 'path': 'Resources/PigeonSimpleDemoConditions.xlsx'},
    {'name': 'Resources/PigeonStatusInstructionsConditions.xlsx', 'path': 'Resources/PigeonStatusInstructionsConditions.xlsx'},
    {'name': 'Resources/PigeonTaskConditions.xlsx', 'path': 'Resources/PigeonTaskConditions.xlsx'},
    {'name': 'Resources/seeds.png', 'path': 'Resources/seeds.png'},
    {'name': 'Resources/pigeon.png', 'path': 'Resources/pigeon.png'},
    {'name': 'default.png', 'path': 'https://pavlovia.org/assets/default/default.png'},
    {'name': 'Resources/cactus.png', 'path': 'Resources/cactus.png'},
    {'name': 'Resources/moon.png', 'path': 'Resources/moon.png'},
    {'name': 'Resources/Pigeon_change_InstructionsConditions.xlsx', 'path': 'Resources/Pigeon_change_InstructionsConditions.xlsx'},
    {'name': 'Resources/Pigeon_fixed_InstructionsConditions.xlsx', 'path': 'Resources/Pigeon_fixed_InstructionsConditions.xlsx'},
    {'name': 'Resources/pigeon.png', 'path': 'Resources/pigeon.png'},
    {'name': 'Resources/PigeonGeneralInstructionsConditions.xlsx', 'path': 'Resources/PigeonGeneralInstructionsConditions.xlsx'},
    {'name': 'Resources/PigeonSimpleDemoConditions.xlsx', 'path': 'Resources/PigeonSimpleDemoConditions.xlsx'},
    {'name': 'Resources/PigeonStatusInstructionsConditions.xlsx', 'path': 'Resources/PigeonStatusInstructionsConditions.xlsx'},
    {'name': 'Resources/PigeonTaskConditions.xlsx', 'path': 'Resources/PigeonTaskConditions.xlsx'},
    {'name': 'Resources/seeds.png', 'path': 'Resources/seeds.png'},
    {'name': 'Resources/sun.png', 'path': 'Resources/sun.png'},
    {'name': 'Resources/tree.png', 'path': 'Resources/tree.png'},
  ]
});

psychoJS.experimentLogger.setLevel(core.Logger.ServerLevel.EXP);


var currentLoop;
var frameDur;
async function updateInfo() {
  currentLoop = psychoJS.experiment;  // right now there are no loops
  expInfo['date'] = util.MonotonicClock.getDateStr();  // add a simple timestamp
  expInfo['expName'] = expName;
  expInfo['psychopyVersion'] = '2023.1.2';
  expInfo['OS'] = window.navigator.platform;


  // store frame rate of monitor if we can measure it successfully
  expInfo['frameRate'] = psychoJS.window.getActualFrameRate();
  if (typeof expInfo['frameRate'] !== 'undefined')
    frameDur = 1.0 / Math.round(expInfo['frameRate']);
  else
    frameDur = 1.0 / 60.0; // couldn't get a reliable measure so guess

  // add info from the URL:
  util.addInfoFromUrl(expInfo);
  psychoJS.setRedirectUrls('https://app.prolific.com/submissions/complete?cc=C1MSKA9I', '');


  
  psychoJS.experiment.dataFileName = (("." + "/") + `data/${expInfo["participant"]}_${expName}_${expInfo["date"]}`);


  return Scheduler.Event.NEXT;
}


var consentClock;
var consent_txt;
var consent_box;
var consent_mouse;
var consent_acknowledge;
var experiment_setupClock;
var exp_type;
var white;
var grey;
var yellow;
var green;
var lightgreen;
var black;
var red;
var ORIGIN_X;
var ORIGIN_Y;
var SEEDS_WIDTH;
var SEEDS_HEIGHT;
var EDGE_DISTANCE;
var ENV_WIDTH;
var ENV_HEIGHT;
var ENV_X;
var ENV_Y;
var SEEDS_SCALE;
var INSTRUCTION_X;
var INSTRUCTION_Y;
var INSTRUCTION_COLOR;
var CHOICE_STRING;
var CONTINUE_STRING;
var CORRECT_STRING;
var ERROR_STRING;
var NO_CHOICE_STRING;
var RT_TOO_FAST_MESSAGE;
var RT_TOO_SLOW_MESSAGE;
var MESSAGE_X;
var MESSAGE_Y;
var instruction_show;
var instruction_string;
var message_show;
var message_string;
var steps_string;
var coins_string;
var high_env_img;
var low_env_img;
var env_img;
var steps_label;
var steps_text;
var coins_text;
var LINE_HEIGHT;
var STATUS_BAR_HEIGHT;
var STATUS_BAR_WIDTH;
var ENV_BAR_HEIGHT;
var ENV_BAR_WIDTH;
var STATUS_BAR_BASE_Y;
var STATUS_BAR_APEX_Y;
var STATUS_BAR_BRACKET_WIDTH;
var ABSCISSA_Y;
var ABSCISSA_WIDTH;
var ORDINATE_Y;
var ORDINATE_WIDTH;
var ORDINATE_HEIGHT;
var COINS_BAR_X;
var COINS_TEXT_X;
var COINS_TEXT_Y;
var COINS_LABEL_TEXT_X;
var COINS_LABEL_TEXT_Y;
var COINS_PROPERTIES_TEXT_X;
var COINS_PROPERTIES_TEXT_Y;
var STEPS_BAR_X;
var STEPS_TEXT_X;
var STEPS_TEXT_Y;
var STEPS_LABEL_TEXT_X;
var STEPS_LABEL_TEXT_Y;
var STEPS_PROPERTIES_TEXT_X;
var STEPS_PROPERTIES_TEXT_Y;
var steps_bar_height;
var steps_bar_center;
var coins_bar_height;
var coins_bar_center;
var env_bar_height;
var env_bar_width;
var env_bar_center;
var seeds_show;
var pigeon_show;
var status_show;
var box_show;
var UPDATE_INTERVAL;
var ITI;
var block_number;
var cal_block_number;
var test_block_number;
var trial_number;
var trial_start;
var bonus_count;
var STEPS_MAX_PER_TRIAL;
var fixed_switch_time;
var fixed_rts_pooled;
var fixed_timeouts_pooled;
var fixed_blocks_done;
var block_order;
var coins_gained_pre;
var coins_lost_pre;
var coins_gained_post;
var coins_lost_post;
var pre_env_img;
var post_env_img;
var RT_WARMUP_TRIALS_TO_DISCARD;
var RT_TOO_FAST_STEPS;
var RT_TOO_SLOW_STEPS;
var RT_TIMEOUT_FRACTION_MAX;
var should_exclude_participant;
var exclusion_message;
var coins_gained_per_correct;
var coins_lost_per_error;
var coins_paid_to_start_trial;
var coins_count;
var coins_max;
var steps_lost_per_error;
var steps_taken_to_start_trial;
var steps_count;
var steps_max;
var step_mean_val;
var step_std_val;
var last_coins_count;
var last_steps_count;
var changepoint;
var pigeon_flip;
var pigeon_true_x;
var pigeon_shown_x;
var pigeon_steps;
var move_pigeon;
var update_status;
var set_trial_end_string;
var set_block_end_string;
var general_instructions_setupClock;
var show_messageClock;
var sm_kbd_continue;
var box_width;
var box_height;
var box_x;
var box_y;
var sm_polygon_box;
var sm_polygon_abscissa;
var sm_polygon_ordinate;
var sm_polygon_petey_midpoint;
var sm_image_right_seeds;
var sm_image_left_seeds;
var sm_image_petey;
var sm_image_env;
var sm_polygon_coin_bar;
var sm_polygon_steps_bar;
var sm_polygon_status_bar_apex;
var sm_polygon_status_bar_base;
var sm_text_coins;
var sm_text_coins_label;
var sm_text_coins_properties;
var sm_text_steps;
var sm_text_steps_label;
var sm_text_steps_properties;
var sm_text_message;
var sm_text_instruction;
var simple_demo_setupClock;
var simple_demoClock;
var sd_polygon_abscissa;
var sd_image_left_seeds;
var sd_image_right_seeds;
var sd_image_pigeon;
var sm_env_img;
var status_instruction_setupClock;
var start_taskClock;
var setup_instructions_messageClock;
var task_runClock;
var otr_kbd_response;
var otr_polygon_abscissa;
var otr_polygon_ordinate;
var otr_polygon_petey_midpoint;
var otr_image_pigeon;
var otr_image_right_seeds;
var otr_image_left_seeds;
var otr_image_env;
var otr_polygon_changepoint_bar;
var otr_polygon_coins_bar;
var otr_polygon_steps_bar;
var otr_polygon_status_bar_apex;
var otr_polygon_status_bar_base;
var otr_text_env;
var otr_text_coins;
var otr_text_coins_label;
var otr_text_coins_properties;
var otr_text_steps;
var otr_text_steps_label;
var otr_text_steps_properties;
var otr_text_instruction;
var final_messageClock;
var show_final_messageClock;
var sfm_kbd_continue;
var sfm_text_message;
var sfm_text_steps_properties;
var sfm_text_steps_label;
var sfm_text_steps;
var sfm_text_coins_properties;
var sfm_text_coins_label;
var sfm_text_coins;
var sfm_polygon_status_bar_base;
var sfm_polygon_status_bar_apex;
var sfm_polygon_steps_bar;
var sfm_polygon_coin_bar;
var sfm_image_petey;
var sfm_image_left_seeds;
var sfm_image_right_seeds;
var sfm_polygon_petey_midpoint;
var sfm_polygon_ordinate;
var sfm_polygon_abscissa;
var sfm_polygon_box;
var sfm_text_instruction;
var globalClock;
var routineTimer;
async function experimentInit() {
  // Initialize components for Routine "consent"
  consentClock = new util.Clock();
  consent_txt = new visual.TextBox({
    win: psychoJS.window,
    name: 'consent_txt',
    text: 'This is an academic research project conducted through the University of Pennsylvania. In this game, a pigeon will wander from the center of the screen to one of two seed piles on the left or right. Your goal is to guess the direction the pigeon will ultimately choose.\n\nThe estimated total time is about 30 minutes.\n\nYou must be at least 18 years old to participate. Your participation in this research is voluntary, which means you can choose whether or not to participate without negative consequences. Your anonymity is assured: the researchers who have requested your participation will not receive any personal information about you except your previously provided Prolific demographic data such as gender, ethnicity, and age. The de-identified data may be stored and distributed for future research studies without additional informed consent.\n\nIf you have questions about this research, please contact Ishan Kalburge by emailing ikalbur1@jhu.edu or Josh Gold by emailing jigold@pennmedicine.upenn.edu.\n\nIf you have questions, concerns, or complaints regarding your participation in this research study, or if you have any questions about your rights as a research subject and you cannot reach a member of the study team, you may contact the Office of Regulatory Affairs at the University of Pennsylvania by calling (215) 898-2614 or emailing irb@pobox.upenn.edu.\n',
    placeholder: 'Type here...',
    font: 'Open Sans',
    pos: [0, 0], 
    letterHeight: 0.023,
    lineSpacing: 1.0,
    size: [0.75, 0.68],  units: undefined, 
    color: 'white', colorSpace: 'rgb',
    fillColor: [(- 0.1765), (- 0.1765), (- 0.1765)], borderColor: undefined,
    languageStyle: 'LTR',
    bold: false, italic: false,
    opacity: undefined,
    padding: 0.0,
    alignment: 'center',
    overflow: 'visible',
    editable: false,
    multiline: true,
    anchor: 'center',
    depth: 0.0 
  });
  
  consent_box = new visual.Rect ({
    win: psychoJS.window, name: 'consent_box', 
    width: [0.05, 0.05][0], height: [0.05, 0.05][1],
    ori: 0.0, pos: [(- 0.4), (- 0.4)],
    anchor: 'center',
    lineWidth: 1.0, 
    colorSpace: 'rgb',
    lineColor: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),
    fillColor: new util.Color('white'),
    opacity: undefined, depth: -1, interpolate: true,
  });
  
  consent_mouse = new core.Mouse({
    win: psychoJS.window,
  });
  consent_mouse.mouseClock = new util.Clock();
  consent_acknowledge = new visual.TextBox({
    win: psychoJS.window,
    name: 'consent_acknowledge',
    text: 'I have read the information above and agree to take part in this study. I understand that I may withdraw my consent at any time before I complete the tasks.',
    placeholder: 'Type here...',
    font: 'Open Sans',
    pos: [(- 0.36), (- 0.42)], 
    letterHeight: 0.023,
    lineSpacing: 1.0,
    size: [0.71, 0.08],  units: undefined, 
    color: 'white', colorSpace: 'rgb',
    fillColor: [(- 0.1765), (- 0.1765), (- 0.1765)], borderColor: undefined,
    languageStyle: 'LTR',
    bold: false, italic: false,
    opacity: undefined,
    padding: 0.0,
    alignment: 'center',
    overflow: 'visible',
    editable: false,
    multiline: true,
    anchor: 'center-left',
    depth: -3.0 
  });
  
  // Initialize components for Routine "experiment_setup"
  experiment_setupClock = new util.Clock();
  // Run 'Begin Experiment' code from es_code_setup
  //
  // Global task configuration, run once at experiment start. Sets up colors, screen
  // geometry, status-bar layout, default reward/step economy, and the shared helper
  // functions (move_pigeon, update_status, set_trial_end_string,
  // set_block_end_string) used throughout task_run and the other routines below.
  //
  // exp_type picks which env image pair frames the block: tree (high reward) / cactus (low
  // reward). The sun/moon ("snr") pair is MXSC's and unused here.
  exp_type = 'reward';
  white = new util.Color([1, 1, 1]);
  grey = new util.Color([0.2, 0.2, 0.2]);
  yellow = new util.Color([1, 1, 0]);
  green = new util.Color([-1, 0, -1]);
  lightgreen = new util.Color([0, 1, 0]);
  black = new util.Color([-1, -1, -1]);
  red = new util.Color([1, 0, 0]);
  ORIGIN_X = 0;
  ORIGIN_Y = 0;
  SEEDS_WIDTH = 0.1;
  SEEDS_HEIGHT = 0.1;
  EDGE_DISTANCE = 0.75;
  ENV_WIDTH = 0.15
  ENV_HEIGHT = 0.1
  ENV_X = EDGE_DISTANCE - 0.1
  ENV_Y = ORIGIN_Y + 0.4
  SEEDS_SCALE = 1;
  INSTRUCTION_X = ORIGIN_X;
  INSTRUCTION_Y = 0.45;
  INSTRUCTION_COLOR = yellow;
  CHOICE_STRING = "Press Left or Right arrow to choose";
  CONTINUE_STRING = "Press Spacebar or any arrow to continue";
  CORRECT_STRING = "Correct";
  ERROR_STRING = "Error";
  NO_CHOICE_STRING = "Failed to respond\nPlease respond more quickly";
  RT_TOO_FAST_MESSAGE = "Session ended early.\n\nYour responses were consistently faster than this task requires to make a real decision. Thank you for participating.";
  RT_TOO_SLOW_MESSAGE = "Session ended early.\n\nYour responses were consistently slower than this task expects, or you were frequently not responding in time. Thank you for participating.";
  MESSAGE_X = ORIGIN_X;
  MESSAGE_Y = 0.3;
  instruction_show = true;
  instruction_string = CONTINUE_STRING;
  message_show = true;
  message_string = "";
  steps_string = " ";
  coins_string = " ";
  if ((exp_type === "reward")) {
      high_env_img = "Resources/tree.png";
      low_env_img = "Resources/cactus.png";
  } else {
      if ((exp_type === "snr")) {
          high_env_img = "Resources/sun.png";
          low_env_img = "Resources/moon.png";
      }
  }
  env_img = high_env_img;
  steps_label = 'Steps remaining';
  steps_text = '200';
  coins_text = '0';
  
  LINE_HEIGHT = 0.1;
  STATUS_BAR_HEIGHT = 0.2;
  STATUS_BAR_WIDTH = 0.1;
  ENV_BAR_HEIGHT = 0.02;
  ENV_BAR_WIDTH = 0.1
  STATUS_BAR_BASE_Y = (ORIGIN_Y - 0.4);
  STATUS_BAR_APEX_Y = (STATUS_BAR_BASE_Y + STATUS_BAR_HEIGHT);
  STATUS_BAR_BRACKET_WIDTH = 0.35;
  ABSCISSA_Y = (ORIGIN_Y - 0.05);
  ABSCISSA_WIDTH = (EDGE_DISTANCE * 2);
  ORDINATE_Y = (ORIGIN_Y + 0.05);
  ORDINATE_WIDTH = 0.2;
  ORDINATE_HEIGHT = 0.01;
  COINS_BAR_X = (- 0.1);
  COINS_TEXT_X = (- 0.1);
  COINS_TEXT_Y = (- 0.37);
  COINS_LABEL_TEXT_X = (- 0.28);
  COINS_LABEL_TEXT_Y = (- 0.2);
  COINS_PROPERTIES_TEXT_X = (- 0.55);
  COINS_PROPERTIES_TEXT_Y = (- 0.3);
  STEPS_BAR_X = 0.1;
  STEPS_TEXT_X = 0.1;
  STEPS_TEXT_Y = (- 0.37);
  STEPS_LABEL_TEXT_X = 0.35;
  STEPS_LABEL_TEXT_Y = (- 0.2);
  STEPS_PROPERTIES_TEXT_X = 0.55;
  STEPS_PROPERTIES_TEXT_Y = (- 0.3);
  steps_bar_height = 0;
  steps_bar_center = 0;
  coins_bar_height = 0;
  coins_bar_center = 0;
  env_bar_height = 0;
  env_bar_width = 0;
  env_bar_center = ENV_X - ENV_BAR_WIDTH/2;
  seeds_show = false;
  pigeon_show = false;
  status_show = false;
  box_show = false;
  UPDATE_INTERVAL = 0.200;
  ITI = 0.7;
  block_number = 0;
  cal_block_number = 0;
  test_block_number = 0;
  trial_number = 0;
  trial_start = true;
  bonus_count = 0;
  
  STEPS_MAX_PER_TRIAL = 50;
  fixed_switch_time = STEPS_MAX_PER_TRIAL;
  fixed_rts_pooled = [];
  fixed_timeouts_pooled = 0;
  fixed_blocks_done = 0;
  block_order = "";
  // RT-extremity exclusion thresholds (in pigeon steps), from the 1st/99th percentiles of
  // per-subject median RT on non-changepoint blocks in the 2026 MXSC data. Checked once, on
  // both fixed blocks pooled, when the second fixed block ends.
  RT_WARMUP_TRIALS_TO_DISCARD = 10;
  RT_TOO_FAST_STEPS = 3;
  RT_TOO_SLOW_STEPS = 25;
  RT_TIMEOUT_FRACTION_MAX = 0.2;
  should_exclude_participant = false;
  exclusion_message = "";
  coins_gained_per_correct = 1;
  coins_lost_per_error = 1;
  coins_paid_to_start_trial = 0;
  coins_count = 0;
  coins_max = 8;
  steps_lost_per_error = 0;
  steps_taken_to_start_trial = 1;
  steps_count = 0;
  steps_max = 11;
  step_mean_val = 0.02;
  step_std_val = 0.1;
  last_coins_count = 0;
  last_steps_count = 0;
  changepoint = false;
  
  pigeon_flip = 0.1;
  pigeon_true_x = 0;
  pigeon_shown_x = pigeon_true_x;
  pigeon_steps = [];
  
  // Advances Petey one step: draws new_step ~ Normal(step_mean, step_std) and adds it to
  // pigeon_true_x (the unclamped position used for the random walk), then clamps the drawn
  // position to +/-EDGE_DISTANCE for display as pigeon_shown_x. pigeon_flip is set from the
  // sign of this single step (not the block's mean direction), so Petey's sprite faces the
  // direction of its most recent move rather than its eventual destination.
  //
  // Gaussian draw is the Marsaglia polar method (a Box-Muller variant): repeatedly sample
  // (u, v) uniform on [-1, 1] until r = u^2+v^2 falls in (0, 1) (i.e. (u,v) lands inside the
  // unit circle, excluding the origin), then u*sqrt(-2*ln(r)/r) is a standard normal
  // variate. The loop caps at 10 attempts; each attempt succeeds independently with
  // probability pi/4, so the chance of exhausting all 10 without a valid (u, v) is
  // ~(1-pi/4)^10 ~ 3e-7 per step. In that vanishingly rare case the loop falls through with
  // r outside (0, 1) (possibly r === 0), making Math.log(r)/r undefined or infinite and
  // producing a NaN step that would permanently derail pigeon_true_x for the rest of that
  // trial (reset again at the next trial_start). Not worth guarding against in practice.
  function move_pigeon_function(step_mean, step_std) {
      var new_step, r, u, v;
      for (var i, _pj_c = 0, _pj_a = util.range(10), _pj_b = _pj_a.length; (_pj_c < _pj_b); _pj_c += 1) {
          i = _pj_a[_pj_c];
          u = ((2 * Math.random()) - 1);
          v = ((2 * Math.random()) - 1);
          r = ((u * u) + (v * v));
          if (((r !== 0) && (r < 1))) {
              break;
          }
      }
      new_step = (step_mean + ((step_std * u) * Math.sqrt((((- 2) * Math.log(r)) / r))));
      if ((new_step > 0)) {
          pigeon_flip = (- 0.1);
      } else {
          pigeon_flip = 0.1;
      }
      pigeon_true_x = (pigeon_true_x + new_step);
      if ((pigeon_true_x >= EDGE_DISTANCE)) {
          pigeon_shown_x = EDGE_DISTANCE;
      } else {
          if ((pigeon_true_x <= (- EDGE_DISTANCE))) {
              pigeon_shown_x = (- EDGE_DISTANCE);
          } else {
              pigeon_shown_x = pigeon_true_x;
          }
      }
  }
  // Recomputes the on-screen coins/steps status-bar text and bar heights, and (for
  // changepoint blocks) the shrinking "steps to changepoint" bar. Each boolean flag opts in
  // to updating that piece of state.
  function update_status_function(update_text, update_coins_bar, update_steps_bar, update_env_bar) {
      if (update_text) {
          coins_string = ("Coins gained per correct choice = " + coins_gained_per_correct.toString()
              + "\nCoins lost per error choice = " + coins_lost_per_error.toString()
              + "\nTarget for bonus = " + coins_max.toString() + " coins");
          steps_string = ("Total steps budget = " + steps_max.toString()
              + "\nSteps to start each trial = " + steps_taken_to_start_trial.toString()
              + "\nExtra steps lost per error = " + steps_lost_per_error.toString());
      }
      if (update_coins_bar) {
          if ((coins_count <= coins_max)) {
              coins_bar_height = ((coins_count / coins_max) * STATUS_BAR_HEIGHT);
          } else {
              coins_bar_height = (STATUS_BAR_HEIGHT + 0.02);
          }
          coins_bar_center = (STATUS_BAR_BASE_Y + (coins_bar_height / 2));
      }
      if (update_steps_bar) {
          steps_bar_height = (((steps_max - steps_count) / steps_max) * STATUS_BAR_HEIGHT);
          steps_bar_center = (STATUS_BAR_BASE_Y + (steps_bar_height / 2));
      }
      if (update_env_bar) {
          env_bar_width = (((switch_time - steps_in_trial) / switch_time) * ENV_BAR_WIDTH);
          if ((steps_in_trial >= switch_time)) {
              env_bar_width = 0;
          }
          env_bar_center = (ENV_X - ENV_BAR_WIDTH/2 + (env_bar_width / 2));
      }
  
  }
  // Builds the between-trial feedback message ("Correct"/"Error"/no-choice + coins and
  // steps delta since the last trial) and rolls last_coins_count/last_steps_count forward
  // so the next call reports only this trial's change.
  function set_trial_end_string_function(feedback_string) {
      var coins_change, coins_feedback_string, steps_change;
      coins_change = (coins_count - last_coins_count);
      steps_change = (steps_count - last_steps_count);
      if ((coins_change > 0)) {
          coins_feedback_string = (coins_change.toString() + " coins gained");
      } else {
          if ((coins_change < 0)) {
              coins_feedback_string = (coins_change.toString() + " coins lost");
          } else {
              coins_feedback_string = "no coins gained or lost";
          }
      }
      message_string = (((((feedback_string + "\n\n") + coins_feedback_string) + "\n\n") + steps_change.toString()) + " steps used this trial");
      last_coins_count = coins_count;
      last_steps_count = steps_count;
  }
  
  // Builds the end-of-block message and awards a bonus (bonus_count += 1, coins bar filled)
  // if coins_count reached coins_max before the step budget ran out.
  function set_block_end_string_function() {
      if ((coins_count >= coins_max)) {
          message_string = "Block finished.\n\nYou earned a bonus. Great job!";
          bonus_count += 1;
          coins_bar_height = STATUS_BAR_HEIGHT;
          coins_bar_center = (STATUS_BAR_BASE_Y + (coins_bar_height / 2));
      } else {
          message_string = "Block finished.\n\nGreat job!";
          coins_bar_height = 0;
          coins_bar_center = STATUS_BAR_BASE_Y;
      }
  }
  
  move_pigeon = move_pigeon_function;
  update_status = update_status_function;
  set_trial_end_string = set_trial_end_string_function;
  set_block_end_string = set_block_end_string_function;
  update_status(true, true, true, false);
  
  // Initialize components for Routine "general_instructions_setup"
  general_instructions_setupClock = new util.Clock();
  // Initialize components for Routine "show_message"
  show_messageClock = new util.Clock();
  sm_kbd_continue = new core.Keyboard({psychoJS: psychoJS, clock: new util.Clock(), waitForStart: true});
  
  // Run 'Begin Experiment' code from sm_code_update
  box_width = 0;
  box_height = 0;
  box_x = 0;
  box_y = 0;
  
  sm_polygon_box = new visual.Rect ({
    win: psychoJS.window, name: 'sm_polygon_box', 
    width: [1.0, 1.0][0], height: [1.0, 1.0][1],
    ori: 0.0, pos: [0, 0],
    anchor: 'center',
    lineWidth: 3.0, 
    colorSpace: 'rgb',
    lineColor: new util.Color([1.0, (- 1.0), (- 1.0)]),
    fillColor: new util.Color([0.0, 0.0, 0.0]),
    opacity: undefined, depth: -2, interpolate: true,
  });
  
  sm_polygon_abscissa = new visual.ShapeStim ({
    win: psychoJS.window, name: 'sm_polygon_abscissa', 
    vertices: [[-[1.0, 1.0][0]/2.0, 0], [+[1.0, 1.0][0]/2.0, 0]],
    ori: 0.0, pos: [0, 0],
    anchor: 'center',
    lineWidth: 2.0, 
    colorSpace: 'rgb',
    lineColor: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),
    fillColor: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),
    opacity: undefined, depth: -3, interpolate: true,
  });
  
  sm_polygon_ordinate = new visual.ShapeStim ({
    win: psychoJS.window, name: 'sm_polygon_ordinate', 
    vertices: [[-[1.0, 1.0][0]/2.0, 0], [+[1.0, 1.0][0]/2.0, 0]],
    ori: 90.0, pos: [0, 0],
    anchor: 'center',
    lineWidth: 2.0, 
    colorSpace: 'rgb',
    lineColor: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),
    fillColor: new util.Color([(- 1), (- 1), (- 1)]),
    opacity: undefined, depth: -4, interpolate: true,
  });
  
  sm_polygon_petey_midpoint = new visual.ShapeStim ({
    win: psychoJS.window, name: 'sm_polygon_petey_midpoint', 
    vertices: [[-[1.0, 1.0][0]/2.0, 0], [+[1.0, 1.0][0]/2.0, 0]],
    ori: 90.0, pos: [0, 0],
    anchor: 'center',
    lineWidth: 2.0, 
    colorSpace: 'rgb',
    lineColor: new util.Color('white'),
    fillColor: new util.Color([0.8824, 0.9451, 1.0]),
    opacity: undefined, depth: -5, interpolate: true,
  });
  
  sm_image_right_seeds = new visual.ImageStim({
    win : psychoJS.window,
    name : 'sm_image_right_seeds', units : undefined, 
    image : 'Resources/seeds.png', mask : undefined,
    anchor : 'center',
    ori : 0.0, pos : [EDGE_DISTANCE, ORIGIN_Y], size : 1.0,
    color : new util.Color([1,1,1]), opacity : undefined,
    flipHoriz : false, flipVert : false,
    texRes : 128.0, interpolate : true, depth : -6.0 
  });
  sm_image_left_seeds = new visual.ImageStim({
    win : psychoJS.window,
    name : 'sm_image_left_seeds', units : undefined, 
    image : 'Resources/seeds.png', mask : undefined,
    anchor : 'center',
    ori : 0.0, pos : [(- EDGE_DISTANCE), ORIGIN_Y], size : 1.0,
    color : new util.Color([1,1,1]), opacity : undefined,
    flipHoriz : false, flipVert : false,
    texRes : 128.0, interpolate : true, depth : -7.0 
  });
  sm_image_petey = new visual.ImageStim({
    win : psychoJS.window,
    name : 'sm_image_petey', units : undefined, 
    image : 'Resources/pigeon.png', mask : undefined,
    anchor : 'center',
    ori : 0.0, pos : [0, 0], size : 1.0,
    color : new util.Color([1,1,1]), opacity : undefined,
    flipHoriz : false, flipVert : false,
    texRes : 128.0, interpolate : true, depth : -8.0 
  });
  sm_image_env = new visual.ImageStim({
    win : psychoJS.window,
    name : 'sm_image_env', units : undefined, 
    image : 'default.png', mask : undefined,
    anchor : 'center',
    ori : 0.0, pos : [ENV_X, ENV_Y], size : [ENV_WIDTH, ENV_HEIGHT],
    color : new util.Color([1,1,1]), opacity : undefined,
    flipHoriz : false, flipVert : false,
    texRes : 128.0, interpolate : true, depth : -9.0 
  });
  sm_polygon_coin_bar = new visual.Rect ({
    win: psychoJS.window, name: 'sm_polygon_coin_bar', 
    width: [1.0, 1.0][0], height: [1.0, 1.0][1],
    ori: 0.0, pos: [0, 0],
    anchor: 'center',
    lineWidth: 1.0, 
    colorSpace: 'rgb',
    lineColor: new util.Color([1.0, 1.0, 1.0]),
    fillColor: new util.Color([1.0, 1.0, 1.0]),
    opacity: undefined, depth: -10, interpolate: true,
  });
  
  sm_polygon_steps_bar = new visual.Rect ({
    win: psychoJS.window, name: 'sm_polygon_steps_bar', 
    width: [1.0, 1.0][0], height: [1.0, 1.0][1],
    ori: 0.0, pos: [0, 0],
    anchor: 'center',
    lineWidth: 1.0, 
    colorSpace: 'rgb',
    lineColor: new util.Color([1.0, 1.0, 1.0]),
    fillColor: new util.Color([1.0, 1.0, 1.0]),
    opacity: undefined, depth: -11, interpolate: true,
  });
  
  sm_polygon_status_bar_apex = new visual.ShapeStim ({
    win: psychoJS.window, name: 'sm_polygon_status_bar_apex', 
    vertices: [[-[1.0, 1.0][0]/2.0, 0], [+[1.0, 1.0][0]/2.0, 0]],
    ori: 0.0, pos: [0, 0],
    anchor: 'center',
    lineWidth: 2.0, 
    colorSpace: 'rgb',
    lineColor: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),
    fillColor: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),
    opacity: undefined, depth: -12, interpolate: true,
  });
  
  sm_polygon_status_bar_base = new visual.ShapeStim ({
    win: psychoJS.window, name: 'sm_polygon_status_bar_base', 
    vertices: [[-[1.0, 1.0][0]/2.0, 0], [+[1.0, 1.0][0]/2.0, 0]],
    ori: 0.0, pos: [0, 0],
    anchor: 'center',
    lineWidth: 2.0, 
    colorSpace: 'rgb',
    lineColor: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),
    fillColor: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),
    opacity: undefined, depth: -13, interpolate: true,
  });
  
  sm_text_coins = new visual.TextStim({
    win: psychoJS.window,
    name: 'sm_text_coins',
    text: '',
    font: 'Open Sans',
    units: undefined, 
    pos: [COINS_TEXT_X, COINS_TEXT_Y], height: 0.03,  wrapWidth: undefined, ori: 0.0,
    languageStyle: 'LTR',
    color: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),  opacity: undefined,
    depth: -14.0 
  });
  
  sm_text_coins_label = new visual.TextStim({
    win: psychoJS.window,
    name: 'sm_text_coins_label',
    text: 'Coins earned',
    font: 'Open Sans',
    units: undefined, 
    pos: [COINS_LABEL_TEXT_X, COINS_LABEL_TEXT_Y], height: 0.03,  wrapWidth: undefined, ori: 0.0,
    languageStyle: 'LTR',
    color: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),  opacity: undefined,
    depth: -15.0 
  });
  
  sm_text_coins_properties = new visual.TextStim({
    win: psychoJS.window,
    name: 'sm_text_coins_properties',
    text: '',
    font: 'Open Sans',
    units: undefined, 
    pos: [COINS_PROPERTIES_TEXT_X, COINS_PROPERTIES_TEXT_Y], height: 0.025,  wrapWidth: undefined, ori: 0.0,
    languageStyle: 'LTR',
    color: new util.Color([1.0, 1.0, 1.0]),  opacity: undefined,
    depth: -16.0 
  });
  
  sm_text_steps = new visual.TextStim({
    win: psychoJS.window,
    name: 'sm_text_steps',
    text: '',
    font: 'Open Sans',
    units: undefined, 
    pos: [STEPS_TEXT_X, STEPS_TEXT_Y], height: 0.03,  wrapWidth: undefined, ori: 0.0,
    languageStyle: 'LTR',
    color: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),  opacity: undefined,
    depth: -17.0 
  });
  
  sm_text_steps_label = new visual.TextStim({
    win: psychoJS.window,
    name: 'sm_text_steps_label',
    text: '',
    font: 'Open Sans',
    units: undefined, 
    pos: [STEPS_LABEL_TEXT_X, STEPS_LABEL_TEXT_Y], height: 0.03,  wrapWidth: undefined, ori: 0.0,
    languageStyle: 'LTR',
    color: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),  opacity: undefined,
    depth: -18.0 
  });
  
  sm_text_steps_properties = new visual.TextStim({
    win: psychoJS.window,
    name: 'sm_text_steps_properties',
    text: '',
    font: 'Open Sans',
    units: undefined, 
    pos: [STEPS_PROPERTIES_TEXT_X, STEPS_PROPERTIES_TEXT_Y], height: 0.025,  wrapWidth: undefined, ori: 0.0,
    languageStyle: 'LTR',
    color: new util.Color([1.0, 1.0, 1.0]),  opacity: undefined,
    depth: -19.0 
  });
  
  sm_text_message = new visual.TextStim({
    win: psychoJS.window,
    name: 'sm_text_message',
    text: '',
    font: 'Open Sans',
    units: undefined, 
    pos: [MESSAGE_X, MESSAGE_Y], height: 0.03,  wrapWidth: undefined, ori: 0.0,
    languageStyle: 'LTR',
    color: new util.Color([1.0, 1.0, 1.0]),  opacity: undefined,
    depth: -20.0 
  });
  
  sm_text_instruction = new visual.TextStim({
    win: psychoJS.window,
    name: 'sm_text_instruction',
    text: '',
    font: 'Open Sans',
    units: undefined, 
    pos: [INSTRUCTION_X, INSTRUCTION_Y], height: 0.02,  wrapWidth: undefined, ori: 0.0,
    languageStyle: 'LTR',
    color: new util.Color(INSTRUCTION_COLOR),  opacity: undefined,
    depth: -21.0 
  });
  
  // Initialize components for Routine "simple_demo_setup"
  simple_demo_setupClock = new util.Clock();
  // Initialize components for Routine "simple_demo"
  simple_demoClock = new util.Clock();
  sd_polygon_abscissa = new visual.ShapeStim ({
    win: psychoJS.window, name: 'sd_polygon_abscissa', 
    vertices: [[-[1.0, 1.0][0]/2.0, 0], [+[1.0, 1.0][0]/2.0, 0]],
    ori: 0.0, pos: [0, 0],
    anchor: 'center',
    lineWidth: 2.0, 
    colorSpace: 'rgb',
    lineColor: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),
    fillColor: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),
    opacity: undefined, depth: -1, interpolate: true,
  });
  
  sd_image_left_seeds = new visual.ImageStim({
    win : psychoJS.window,
    name : 'sd_image_left_seeds', units : undefined, 
    image : 'Resources/seeds.png', mask : undefined,
    anchor : 'center',
    ori : 0.0, pos : [(- EDGE_DISTANCE), ORIGIN_Y], size : 1.0,
    color : new util.Color([1,1,1]), opacity : undefined,
    flipHoriz : false, flipVert : false,
    texRes : 128.0, interpolate : true, depth : -2.0 
  });
  sd_image_right_seeds = new visual.ImageStim({
    win : psychoJS.window,
    name : 'sd_image_right_seeds', units : undefined, 
    image : 'Resources/seeds.png', mask : undefined,
    anchor : 'center',
    ori : 0.0, pos : [EDGE_DISTANCE, ORIGIN_Y], size : 1.0,
    color : new util.Color([1,1,1]), opacity : undefined,
    flipHoriz : false, flipVert : false,
    texRes : 128.0, interpolate : true, depth : -3.0 
  });
  sd_image_pigeon = new visual.ImageStim({
    win : psychoJS.window,
    name : 'sd_image_pigeon', units : undefined, 
    image : 'Resources/pigeon.png', mask : undefined,
    anchor : 'center',
    ori : 0.0, pos : [0, 0], size : 1.0,
    color : new util.Color([1,1,1]), opacity : undefined,
    flipHoriz : false, flipVert : false,
    texRes : 128.0, interpolate : true, depth : -4.0 
  });
  sm_env_img = new visual.ImageStim({
    win : psychoJS.window,
    name : 'sm_env_img', units : undefined, 
    image : 'default.png', mask : undefined,
    anchor : 'center',
    ori : 0.0, pos : [ENV_X, ENV_Y], size : [ENV_WIDTH, ENV_HEIGHT],
    color : new util.Color([1,1,1]), opacity : undefined,
    flipHoriz : false, flipVert : false,
    texRes : 128.0, interpolate : true, depth : -5.0 
  });
  // Initialize components for Routine "status_instruction_setup"
  status_instruction_setupClock = new util.Clock();
  // Initialize components for Routine "start_task"
  start_taskClock = new util.Clock();
  // Initialize components for Routine "setup_instructions_message"
  setup_instructions_messageClock = new util.Clock();
  // Initialize components for Routine "task_run"
  task_runClock = new util.Clock();
  otr_kbd_response = new core.Keyboard({psychoJS: psychoJS, clock: new util.Clock(), waitForStart: true});
  
  otr_polygon_abscissa = new visual.ShapeStim ({
    win: psychoJS.window, name: 'otr_polygon_abscissa', 
    vertices: [[-[1.0, 1.0][0]/2.0, 0], [+[1.0, 1.0][0]/2.0, 0]],
    ori: 0.0, pos: [0, 0],
    anchor: 'center',
    lineWidth: 2.0, 
    colorSpace: 'rgb',
    lineColor: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),
    fillColor: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),
    opacity: undefined, depth: -2, interpolate: true,
  });
  
  otr_polygon_ordinate = new visual.ShapeStim ({
    win: psychoJS.window, name: 'otr_polygon_ordinate', 
    vertices: [[-[1.0, 1.0][0]/2.0, 0], [+[1.0, 1.0][0]/2.0, 0]],
    ori: 90.0, pos: [0, 0],
    anchor: 'center',
    lineWidth: 2.0, 
    colorSpace: 'rgb',
    lineColor: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),
    fillColor: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),
    opacity: undefined, depth: -3, interpolate: true,
  });
  
  otr_polygon_petey_midpoint = new visual.ShapeStim ({
    win: psychoJS.window, name: 'otr_polygon_petey_midpoint', 
    vertices: [[-[1.0, 1.0][0]/2.0, 0], [+[1.0, 1.0][0]/2.0, 0]],
    ori: 90.0, pos: [0, 0],
    anchor: 'center',
    lineWidth: 2.0, 
    colorSpace: 'rgb',
    lineColor: new util.Color('white'),
    fillColor: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),
    opacity: undefined, depth: -4, interpolate: true,
  });
  
  otr_image_pigeon = new visual.ImageStim({
    win : psychoJS.window,
    name : 'otr_image_pigeon', units : undefined, 
    image : 'Resources/pigeon.png', mask : undefined,
    anchor : 'center',
    ori : 0.0, pos : [0, 0], size : 1.0,
    color : new util.Color([1,1,1]), opacity : undefined,
    flipHoriz : false, flipVert : false,
    texRes : 128.0, interpolate : true, depth : -5.0 
  });
  otr_image_right_seeds = new visual.ImageStim({
    win : psychoJS.window,
    name : 'otr_image_right_seeds', units : undefined, 
    image : 'Resources/seeds.png', mask : undefined,
    anchor : 'center',
    ori : 0.0, pos : [EDGE_DISTANCE, ORIGIN_Y], size : 1.0,
    color : new util.Color([1,1,1]), opacity : undefined,
    flipHoriz : false, flipVert : false,
    texRes : 128.0, interpolate : true, depth : -6.0 
  });
  otr_image_left_seeds = new visual.ImageStim({
    win : psychoJS.window,
    name : 'otr_image_left_seeds', units : undefined, 
    image : 'Resources/seeds.png', mask : undefined,
    anchor : 'center',
    ori : 0.0, pos : [(- EDGE_DISTANCE), ORIGIN_Y], size : 1.0,
    color : new util.Color([1,1,1]), opacity : undefined,
    flipHoriz : false, flipVert : false,
    texRes : 128.0, interpolate : true, depth : -7.0 
  });
  otr_image_env = new visual.ImageStim({
    win : psychoJS.window,
    name : 'otr_image_env', units : undefined, 
    image : 'default.png', mask : undefined,
    anchor : 'center',
    ori : 0.0, pos : [ENV_X, ENV_Y], size : [ENV_WIDTH, ENV_HEIGHT],
    color : new util.Color([1,1,1]), opacity : undefined,
    flipHoriz : false, flipVert : false,
    texRes : 128.0, interpolate : true, depth : -8.0 
  });
  otr_polygon_changepoint_bar = new visual.Rect ({
    win: psychoJS.window, name: 'otr_polygon_changepoint_bar', 
    width: [1.0, 1.0][0], height: [1.0, 1.0][1],
    ori: 0.0, pos: [0, 0],
    anchor: 'center',
    lineWidth: 1.0, 
    colorSpace: 'rgb',
    lineColor: new util.Color('white'),
    fillColor: new util.Color('white'),
    opacity: undefined, depth: -9, interpolate: true,
  });
  
  otr_polygon_coins_bar = new visual.Rect ({
    win: psychoJS.window, name: 'otr_polygon_coins_bar', 
    width: [1.0, 1.0][0], height: [1.0, 1.0][1],
    ori: 0.0, pos: [0, 0],
    anchor: 'center',
    lineWidth: 1.0, 
    colorSpace: 'rgb',
    lineColor: new util.Color('white'),
    fillColor: new util.Color('white'),
    opacity: undefined, depth: -10, interpolate: true,
  });
  
  otr_polygon_steps_bar = new visual.Rect ({
    win: psychoJS.window, name: 'otr_polygon_steps_bar', 
    width: [1.0, 1.0][0], height: [1.0, 1.0][1],
    ori: 0.0, pos: [0, 0],
    anchor: 'center',
    lineWidth: 1.0, 
    colorSpace: 'rgb',
    lineColor: new util.Color('white'),
    fillColor: new util.Color('white'),
    opacity: undefined, depth: -11, interpolate: true,
  });
  
  otr_polygon_status_bar_apex = new visual.ShapeStim ({
    win: psychoJS.window, name: 'otr_polygon_status_bar_apex', 
    vertices: [[-[1.0, 1.0][0]/2.0, 0], [+[1.0, 1.0][0]/2.0, 0]],
    ori: 0.0, pos: [0, 0],
    anchor: 'center',
    lineWidth: 2.0, 
    colorSpace: 'rgb',
    lineColor: new util.Color('black'),
    fillColor: new util.Color('black'),
    opacity: undefined, depth: -12, interpolate: true,
  });
  
  otr_polygon_status_bar_base = new visual.ShapeStim ({
    win: psychoJS.window, name: 'otr_polygon_status_bar_base', 
    vertices: [[-[1.0, 1.0][0]/2.0, 0], [+[1.0, 1.0][0]/2.0, 0]],
    ori: 0.0, pos: [0, 0],
    anchor: 'center',
    lineWidth: 2.0, 
    colorSpace: 'rgb',
    lineColor: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),
    fillColor: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),
    opacity: undefined, depth: -13, interpolate: true,
  });
  
  otr_text_env = new visual.TextStim({
    win: psychoJS.window,
    name: 'otr_text_env',
    text: '',
    font: 'Open Sans',
    units: undefined, 
    pos: [((ENV_X + (ENV_BAR_WIDTH / 2)) + 0.02), (ENV_Y - 0.06)], height: 0.03,  wrapWidth: undefined, ori: 0.0,
    languageStyle: 'LTR',
    color: new util.Color([1.0, 1.0, 1.0]),  opacity: undefined,
    depth: -14.0 
  });
  
  otr_text_coins = new visual.TextStim({
    win: psychoJS.window,
    name: 'otr_text_coins',
    text: '',
    font: 'Open Sans',
    units: undefined, 
    pos: [COINS_TEXT_X, COINS_TEXT_Y], height: 0.03,  wrapWidth: undefined, ori: 0.0,
    languageStyle: 'LTR',
    color: new util.Color('black'),  opacity: undefined,
    depth: -15.0 
  });
  
  otr_text_coins_label = new visual.TextStim({
    win: psychoJS.window,
    name: 'otr_text_coins_label',
    text: 'Coins earned',
    font: 'Open Sans',
    units: undefined, 
    pos: [COINS_LABEL_TEXT_X, COINS_LABEL_TEXT_Y], height: 0.03,  wrapWidth: undefined, ori: 0.0,
    languageStyle: 'LTR',
    color: new util.Color('black'),  opacity: undefined,
    depth: -16.0 
  });
  
  otr_text_coins_properties = new visual.TextStim({
    win: psychoJS.window,
    name: 'otr_text_coins_properties',
    text: '',
    font: 'Open Sans',
    units: undefined, 
    pos: [COINS_PROPERTIES_TEXT_X, COINS_PROPERTIES_TEXT_Y], height: 0.025,  wrapWidth: undefined, ori: 0.0,
    languageStyle: 'LTR',
    color: new util.Color('white'),  opacity: undefined,
    depth: -17.0 
  });
  
  otr_text_steps = new visual.TextStim({
    win: psychoJS.window,
    name: 'otr_text_steps',
    text: '',
    font: 'Open Sans',
    units: undefined, 
    pos: [STEPS_TEXT_X, STEPS_TEXT_Y], height: 0.03,  wrapWidth: undefined, ori: 0.0,
    languageStyle: 'LTR',
    color: new util.Color('black'),  opacity: undefined,
    depth: -18.0 
  });
  
  otr_text_steps_label = new visual.TextStim({
    win: psychoJS.window,
    name: 'otr_text_steps_label',
    text: '',
    font: 'Open Sans',
    units: undefined, 
    pos: [STEPS_LABEL_TEXT_X, STEPS_LABEL_TEXT_Y], height: 0.03,  wrapWidth: undefined, ori: 0.0,
    languageStyle: 'LTR',
    color: new util.Color('black'),  opacity: undefined,
    depth: -19.0 
  });
  
  otr_text_steps_properties = new visual.TextStim({
    win: psychoJS.window,
    name: 'otr_text_steps_properties',
    text: '',
    font: 'Open Sans',
    units: undefined, 
    pos: [STEPS_PROPERTIES_TEXT_X, STEPS_PROPERTIES_TEXT_Y], height: 0.025,  wrapWidth: undefined, ori: 0.0,
    languageStyle: 'LTR',
    color: new util.Color('white'),  opacity: undefined,
    depth: -20.0 
  });
  
  otr_text_instruction = new visual.TextStim({
    win: psychoJS.window,
    name: 'otr_text_instruction',
    text: '',
    font: 'Open Sans',
    units: undefined, 
    pos: [INSTRUCTION_X, INSTRUCTION_Y], height: 0.02,  wrapWidth: undefined, ori: 0.0,
    languageStyle: 'LTR',
    color: new util.Color(INSTRUCTION_COLOR),  opacity: undefined,
    depth: -21.0 
  });
  
  // Initialize components for Routine "final_message"
  final_messageClock = new util.Clock();
  // Initialize components for Routine "show_final_message"
  show_final_messageClock = new util.Clock();
  sfm_kbd_continue = new core.Keyboard({psychoJS: psychoJS, clock: new util.Clock(), waitForStart: true});
  
  // Run 'Begin Experiment' code from sfm_code_update
  box_width = 0;
  box_height = 0;
  box_x = 0;
  box_y = 0;
  
  sfm_text_message = new visual.TextStim({
    win: psychoJS.window,
    name: 'sfm_text_message',
    text: '',
    font: 'Open Sans',
    units: undefined, 
    pos: [MESSAGE_X, MESSAGE_Y], height: 0.03,  wrapWidth: undefined, ori: 0.0,
    languageStyle: 'LTR',
    color: new util.Color([1.0, 1.0, 1.0]),  opacity: undefined,
    depth: -2.0 
  });
  
  sfm_text_steps_properties = new visual.TextStim({
    win: psychoJS.window,
    name: 'sfm_text_steps_properties',
    text: '',
    font: 'Open Sans',
    units: undefined, 
    pos: [STEPS_PROPERTIES_TEXT_X, STEPS_PROPERTIES_TEXT_Y], height: 0.025,  wrapWidth: undefined, ori: 0.0,
    languageStyle: 'LTR',
    color: new util.Color([1.0, 1.0, 1.0]),  opacity: undefined,
    depth: -3.0 
  });
  
  sfm_text_steps_label = new visual.TextStim({
    win: psychoJS.window,
    name: 'sfm_text_steps_label',
    text: 'Steps remaining',
    font: 'Open Sans',
    units: undefined, 
    pos: [STEPS_LABEL_TEXT_X, STEPS_LABEL_TEXT_Y], height: 0.03,  wrapWidth: undefined, ori: 0.0,
    languageStyle: 'LTR',
    color: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),  opacity: undefined,
    depth: -4.0 
  });
  
  sfm_text_steps = new visual.TextStim({
    win: psychoJS.window,
    name: 'sfm_text_steps',
    text: '',
    font: 'Open Sans',
    units: undefined, 
    pos: [STEPS_TEXT_X, STEPS_TEXT_Y], height: 0.03,  wrapWidth: undefined, ori: 0.0,
    languageStyle: 'LTR',
    color: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),  opacity: undefined,
    depth: -5.0 
  });
  
  sfm_text_coins_properties = new visual.TextStim({
    win: psychoJS.window,
    name: 'sfm_text_coins_properties',
    text: '',
    font: 'Open Sans',
    units: undefined, 
    pos: [COINS_PROPERTIES_TEXT_X, COINS_PROPERTIES_TEXT_Y], height: 0.025,  wrapWidth: undefined, ori: 0.0,
    languageStyle: 'LTR',
    color: new util.Color([1.0, 1.0, 1.0]),  opacity: undefined,
    depth: -6.0 
  });
  
  sfm_text_coins_label = new visual.TextStim({
    win: psychoJS.window,
    name: 'sfm_text_coins_label',
    text: 'Coins earned',
    font: 'Open Sans',
    units: undefined, 
    pos: [COINS_LABEL_TEXT_X, COINS_LABEL_TEXT_Y], height: 0.03,  wrapWidth: undefined, ori: 0.0,
    languageStyle: 'LTR',
    color: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),  opacity: undefined,
    depth: -7.0 
  });
  
  sfm_text_coins = new visual.TextStim({
    win: psychoJS.window,
    name: 'sfm_text_coins',
    text: '',
    font: 'Open Sans',
    units: undefined, 
    pos: [COINS_TEXT_X, COINS_TEXT_Y], height: 0.03,  wrapWidth: undefined, ori: 0.0,
    languageStyle: 'LTR',
    color: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),  opacity: undefined,
    depth: -8.0 
  });
  
  sfm_polygon_status_bar_base = new visual.ShapeStim ({
    win: psychoJS.window, name: 'sfm_polygon_status_bar_base', 
    vertices: [[-[1.0, 1.0][0]/2.0, 0], [+[1.0, 1.0][0]/2.0, 0]],
    ori: 0.0, pos: [0, 0],
    anchor: 'center',
    lineWidth: 2.0, 
    colorSpace: 'rgb',
    lineColor: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),
    fillColor: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),
    opacity: undefined, depth: -9, interpolate: true,
  });
  
  sfm_polygon_status_bar_apex = new visual.ShapeStim ({
    win: psychoJS.window, name: 'sfm_polygon_status_bar_apex', 
    vertices: [[-[1.0, 1.0][0]/2.0, 0], [+[1.0, 1.0][0]/2.0, 0]],
    ori: 0.0, pos: [0, 0],
    anchor: 'center',
    lineWidth: 2.0, 
    colorSpace: 'rgb',
    lineColor: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),
    fillColor: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),
    opacity: undefined, depth: -10, interpolate: true,
  });
  
  sfm_polygon_steps_bar = new visual.Rect ({
    win: psychoJS.window, name: 'sfm_polygon_steps_bar', 
    width: [1.0, 1.0][0], height: [1.0, 1.0][1],
    ori: 0.0, pos: [0, 0],
    anchor: 'center',
    lineWidth: 1.0, 
    colorSpace: 'rgb',
    lineColor: new util.Color([1.0, 1.0, 1.0]),
    fillColor: new util.Color([1.0, 1.0, 1.0]),
    opacity: undefined, depth: -11, interpolate: true,
  });
  
  sfm_polygon_coin_bar = new visual.Rect ({
    win: psychoJS.window, name: 'sfm_polygon_coin_bar', 
    width: [1.0, 1.0][0], height: [1.0, 1.0][1],
    ori: 0.0, pos: [0, 0],
    anchor: 'center',
    lineWidth: 1.0, 
    colorSpace: 'rgb',
    lineColor: new util.Color([1.0, 1.0, 1.0]),
    fillColor: new util.Color([1.0, 1.0, 1.0]),
    opacity: undefined, depth: -12, interpolate: true,
  });
  
  sfm_image_petey = new visual.ImageStim({
    win : psychoJS.window,
    name : 'sfm_image_petey', units : undefined, 
    image : 'Resources/pigeon.png', mask : undefined,
    anchor : 'center',
    ori : 0.0, pos : [0, 0], size : 1.0,
    color : new util.Color([1,1,1]), opacity : undefined,
    flipHoriz : false, flipVert : false,
    texRes : 128.0, interpolate : true, depth : -13.0 
  });
  sfm_image_left_seeds = new visual.ImageStim({
    win : psychoJS.window,
    name : 'sfm_image_left_seeds', units : undefined, 
    image : 'Resources/seeds.png', mask : undefined,
    anchor : 'center',
    ori : 0.0, pos : [(- EDGE_DISTANCE), ORIGIN_Y], size : [SEEDS_WIDTH, SEEDS_HEIGHT],
    color : new util.Color([1,1,1]), opacity : undefined,
    flipHoriz : false, flipVert : false,
    texRes : 128.0, interpolate : true, depth : -14.0 
  });
  sfm_image_right_seeds = new visual.ImageStim({
    win : psychoJS.window,
    name : 'sfm_image_right_seeds', units : undefined, 
    image : 'Resources/seeds.png', mask : undefined,
    anchor : 'center',
    ori : 0.0, pos : [EDGE_DISTANCE, ORIGIN_Y], size : [SEEDS_WIDTH, SEEDS_HEIGHT],
    color : new util.Color([1,1,1]), opacity : undefined,
    flipHoriz : false, flipVert : false,
    texRes : 128.0, interpolate : true, depth : -15.0 
  });
  sfm_polygon_petey_midpoint = new visual.ShapeStim ({
    win: psychoJS.window, name: 'sfm_polygon_petey_midpoint', 
    vertices: [[-[1.0, 1.0][0]/2.0, 0], [+[1.0, 1.0][0]/2.0, 0]],
    ori: 90.0, pos: [0, 0],
    anchor: 'center',
    lineWidth: 2.0, 
    colorSpace: 'rgb',
    lineColor: new util.Color([1.0, (- 1.0), (- 1.0)]),
    fillColor: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),
    opacity: undefined, depth: -16, interpolate: true,
  });
  
  sfm_polygon_ordinate = new visual.ShapeStim ({
    win: psychoJS.window, name: 'sfm_polygon_ordinate', 
    vertices: [[-[1.0, 1.0][0]/2.0, 0], [+[1.0, 1.0][0]/2.0, 0]],
    ori: 90.0, pos: [0, 0],
    anchor: 'center',
    lineWidth: 2.0, 
    colorSpace: 'rgb',
    lineColor: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),
    fillColor: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),
    opacity: undefined, depth: -17, interpolate: true,
  });
  
  sfm_polygon_abscissa = new visual.ShapeStim ({
    win: psychoJS.window, name: 'sfm_polygon_abscissa', 
    vertices: [[-[1.0, 1.0][0]/2.0, 0], [+[1.0, 1.0][0]/2.0, 0]],
    ori: 0.0, pos: [0, 0],
    anchor: 'center',
    lineWidth: 2.0, 
    colorSpace: 'rgb',
    lineColor: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),
    fillColor: new util.Color([(- 1.0), (- 1.0), (- 1.0)]),
    opacity: undefined, depth: -18, interpolate: true,
  });
  
  sfm_polygon_box = new visual.Rect ({
    win: psychoJS.window, name: 'sfm_polygon_box', 
    width: [1.0, 1.0][0], height: [1.0, 1.0][1],
    ori: 0.0, pos: [0, 0],
    anchor: 'center',
    lineWidth: 3.0, 
    colorSpace: 'rgb',
    lineColor: new util.Color([1.0, (- 1.0), (- 1.0)]),
    fillColor: new util.Color([0.0, 0.0, 0.0]),
    opacity: undefined, depth: -19, interpolate: true,
  });
  
  sfm_text_instruction = new visual.TextStim({
    win: psychoJS.window,
    name: 'sfm_text_instruction',
    text: '',
    font: 'Open Sans',
    units: undefined, 
    pos: [INSTRUCTION_X, INSTRUCTION_Y], height: 0.02,  wrapWidth: undefined, ori: 0.0,
    languageStyle: 'LTR',
    color: new util.Color(INSTRUCTION_COLOR),  opacity: undefined,
    depth: -20.0 
  });
  
  // Create some handy timers
  globalClock = new util.Clock();  // to track the time since experiment started
  routineTimer = new util.CountdownTimer();  // to track time remaining of each (non-slip) routine
  
  return Scheduler.Event.NEXT;
}


var t;
var frameN;
var continueRoutine;
var gotValidClick;
var consentComponents;
function consentRoutineBegin(snapshot) {
  return async function () {
    TrialHandler.fromSnapshot(snapshot); // ensure that .thisN vals are up to date
    
    //--- Prepare to start Routine 'consent' ---
    t = 0;
    consentClock.reset(); // clock
    frameN = -1;
    continueRoutine = true; // until we're told otherwise
    // update component parameters for each repeat
    // setup some python lists for storing info about the consent_mouse
    consent_mouse.clicked_name = [];
    gotValidClick = false; // until a click is received
    // keep track of which components have finished
    consentComponents = [];
    consentComponents.push(consent_txt);
    consentComponents.push(consent_box);
    consentComponents.push(consent_mouse);
    consentComponents.push(consent_acknowledge);
    
    for (const thisComponent of consentComponents)
      if ('status' in thisComponent)
        thisComponent.status = PsychoJS.Status.NOT_STARTED;
    return Scheduler.Event.NEXT;
  }
}


var prevButtonState;
var _mouseButtons;
function consentRoutineEachFrame() {
  return async function () {
    //--- Loop for each frame of Routine 'consent' ---
    // get current time
    t = consentClock.getTime();
    frameN = frameN + 1;// number of completed frames (so 0 is the first frame)
    // update/draw components on each frame
    
    // *consent_txt* updates
    if (t >= 0.0 && consent_txt.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      consent_txt.tStart = t;  // (not accounting for frame time here)
      consent_txt.frameNStart = frameN;  // exact frame index
      
      consent_txt.setAutoDraw(true);
    }

    
    // *consent_box* updates
    if (t >= 0.0 && consent_box.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      consent_box.tStart = t;  // (not accounting for frame time here)
      consent_box.frameNStart = frameN;  // exact frame index
      
      consent_box.setAutoDraw(true);
    }

    // *consent_mouse* updates
    if (t >= 0.0 && consent_mouse.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      consent_mouse.tStart = t;  // (not accounting for frame time here)
      consent_mouse.frameNStart = frameN;  // exact frame index
      
      consent_mouse.status = PsychoJS.Status.STARTED;
      consent_mouse.mouseClock.reset();
      prevButtonState = consent_mouse.getPressed();  // if button is down already this ISN'T a new click
      }
    if (consent_mouse.status === PsychoJS.Status.STARTED) {  // only update if started and not finished!
      _mouseButtons = consent_mouse.getPressed();
      if (!_mouseButtons.every( (e,i,) => (e == prevButtonState[i]) )) { // button state changed?
        prevButtonState = _mouseButtons;
        if (_mouseButtons.reduce( (e, acc) => (e+acc) ) > 0) { // state changed to a new click
          // check if the mouse was inside our 'clickable' objects
          gotValidClick = false;
          for (const obj of [consent_box]) {
            if (obj.contains(consent_mouse)) {
              gotValidClick = true;
              consent_mouse.clicked_name.push(obj.name)
            }
          }
          if (gotValidClick === true) { // end routine on response
            continueRoutine = false;
          }
        }
      }
    }
    
    // *consent_acknowledge* updates
    if (t >= 0.0 && consent_acknowledge.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      consent_acknowledge.tStart = t;  // (not accounting for frame time here)
      consent_acknowledge.frameNStart = frameN;  // exact frame index
      
      consent_acknowledge.setAutoDraw(true);
    }

    // check for quit (typically the Esc key)
    if (psychoJS.experiment.experimentEnded || psychoJS.eventManager.getKeys({keyList:['escape']}).length > 0) {
      return quitPsychoJS('The [Escape] key was pressed. Goodbye!', false);
    }
    
    // check if the Routine should terminate
    if (!continueRoutine) {  // a component has requested a forced-end of Routine
      return Scheduler.Event.NEXT;
    }
    
    continueRoutine = false;  // reverts to True if at least one component still running
    for (const thisComponent of consentComponents)
      if ('status' in thisComponent && thisComponent.status !== PsychoJS.Status.FINISHED) {
        continueRoutine = true;
        break;
      }
    
    // refresh the screen if continuing
    if (continueRoutine) {
      return Scheduler.Event.FLIP_REPEAT;
    } else {
      return Scheduler.Event.NEXT;
    }
  };
}


var _mouseXYs;
function consentRoutineEnd(snapshot) {
  return async function () {
    //--- Ending Routine 'consent' ---
    for (const thisComponent of consentComponents) {
      if (typeof thisComponent.setAutoDraw === 'function') {
        thisComponent.setAutoDraw(false);
      }
    }
    // store data for psychoJS.experiment (ExperimentHandler)
    _mouseXYs = consent_mouse.getPos();
    _mouseButtons = consent_mouse.getPressed();
    psychoJS.experiment.addData('consent_mouse.x', _mouseXYs[0]);
    psychoJS.experiment.addData('consent_mouse.y', _mouseXYs[1]);
    psychoJS.experiment.addData('consent_mouse.leftButton', _mouseButtons[0]);
    psychoJS.experiment.addData('consent_mouse.midButton', _mouseButtons[1]);
    psychoJS.experiment.addData('consent_mouse.rightButton', _mouseButtons[2]);
    if (consent_mouse.clicked_name.length > 0) {
      psychoJS.experiment.addData('consent_mouse.clicked_name', consent_mouse.clicked_name[0]);}
    // the Routine "consent" was not non-slip safe, so reset the non-slip timer
    routineTimer.reset();
    
    // Routines running outside a loop should always advance the datafile row
    if (currentLoop === psychoJS.experiment) {
      psychoJS.experiment.nextEntry(snapshot);
    }
    return Scheduler.Event.NEXT;
  }
}


var experiment_setupComponents;
function experiment_setupRoutineBegin(snapshot) {
  return async function () {
    TrialHandler.fromSnapshot(snapshot); // ensure that .thisN vals are up to date
    
    //--- Prepare to start Routine 'experiment_setup' ---
    t = 0;
    experiment_setupClock.reset(); // clock
    frameN = -1;
    continueRoutine = true; // until we're told otherwise
    // update component parameters for each repeat
    // keep track of which components have finished
    experiment_setupComponents = [];
    
    for (const thisComponent of experiment_setupComponents)
      if ('status' in thisComponent)
        thisComponent.status = PsychoJS.Status.NOT_STARTED;
    return Scheduler.Event.NEXT;
  }
}


function experiment_setupRoutineEachFrame() {
  return async function () {
    //--- Loop for each frame of Routine 'experiment_setup' ---
    // get current time
    t = experiment_setupClock.getTime();
    frameN = frameN + 1;// number of completed frames (so 0 is the first frame)
    // update/draw components on each frame
    // check for quit (typically the Esc key)
    if (psychoJS.experiment.experimentEnded || psychoJS.eventManager.getKeys({keyList:['escape']}).length > 0) {
      return quitPsychoJS('The [Escape] key was pressed. Goodbye!', false);
    }
    
    // check if the Routine should terminate
    if (!continueRoutine) {  // a component has requested a forced-end of Routine
      return Scheduler.Event.NEXT;
    }
    
    continueRoutine = false;  // reverts to True if at least one component still running
    for (const thisComponent of experiment_setupComponents)
      if ('status' in thisComponent && thisComponent.status !== PsychoJS.Status.FINISHED) {
        continueRoutine = true;
        break;
      }
    
    // refresh the screen if continuing
    if (continueRoutine) {
      return Scheduler.Event.FLIP_REPEAT;
    } else {
      return Scheduler.Event.NEXT;
    }
  };
}


function experiment_setupRoutineEnd(snapshot) {
  return async function () {
    //--- Ending Routine 'experiment_setup' ---
    for (const thisComponent of experiment_setupComponents) {
      if (typeof thisComponent.setAutoDraw === 'function') {
        thisComponent.setAutoDraw(false);
      }
    }
    // the Routine "experiment_setup" was not non-slip safe, so reset the non-slip timer
    routineTimer.reset();
    
    // Routines running outside a loop should always advance the datafile row
    if (currentLoop === psychoJS.experiment) {
      psychoJS.experiment.nextEntry(snapshot);
    }
    return Scheduler.Event.NEXT;
  }
}


// LOOP "general_instructions_loop": 1 pass over PigeonGeneralInstructionsConditions.xlsx,
// one general_instructions_setup + show_message per row.
var general_instructions_loop;
function general_instructions_loopLoopBegin(general_instructions_loopLoopScheduler, snapshot) {
  return async function() {
    TrialHandler.fromSnapshot(snapshot); // update internal variables (.thisN etc) of the loop
    
    // set up handler to look after randomisation of conditions etc
    general_instructions_loop = new TrialHandler({
      psychoJS: psychoJS,
      nReps: 1, method: TrialHandler.Method.SEQUENTIAL,
      extraInfo: expInfo, originPath: undefined,
      trialList: 'Resources/PigeonGeneralInstructionsConditions.xlsx',
      seed: undefined, name: 'general_instructions_loop'
    });
    psychoJS.experiment.addLoop(general_instructions_loop); // add the loop to the experiment
    currentLoop = general_instructions_loop;  // we're now the current loop
    
    // Schedule all the trials in the trialList:
    for (const thisGeneral_instructions_loop of general_instructions_loop) {
      snapshot = general_instructions_loop.getSnapshot();
      general_instructions_loopLoopScheduler.add(importConditions(snapshot));
      general_instructions_loopLoopScheduler.add(general_instructions_setupRoutineBegin(snapshot));
      general_instructions_loopLoopScheduler.add(general_instructions_setupRoutineEachFrame());
      general_instructions_loopLoopScheduler.add(general_instructions_setupRoutineEnd(snapshot));
      general_instructions_loopLoopScheduler.add(show_messageRoutineBegin(snapshot));
      general_instructions_loopLoopScheduler.add(show_messageRoutineEachFrame());
      general_instructions_loopLoopScheduler.add(show_messageRoutineEnd(snapshot));
      general_instructions_loopLoopScheduler.add(general_instructions_loopLoopEndIteration(general_instructions_loopLoopScheduler, snapshot));
    }
    
    return Scheduler.Event.NEXT;
  }
}


async function general_instructions_loopLoopEnd() {
  // terminate loop
  psychoJS.experiment.removeLoop(general_instructions_loop);
  // update the current loop from the ExperimentHandler
  if (psychoJS.experiment._unfinishedLoops.length>0)
    currentLoop = psychoJS.experiment._unfinishedLoops.at(-1);
  else
    currentLoop = psychoJS.experiment;  // so we use addData from the experiment
  return Scheduler.Event.NEXT;
}


function general_instructions_loopLoopEndIteration(scheduler, snapshot) {
  // ------Prepare for next entry------
  return async function () {
    if (typeof snapshot !== 'undefined') {
      // ------Check if user ended loop early------
      if (snapshot.finished) {
        // Check for and save orphaned data
        if (psychoJS.experiment.isEntryEmpty()) {
          psychoJS.experiment.nextEntry(snapshot);
        }
        scheduler.stop();
      }
    return Scheduler.Event.NEXT;
    }
  };
}


// LOOP "simple_demo_block_loop": 1 pass over PigeonSimpleDemoConditions.xlsx (one practice
// demo block per row); each iteration runs simple_demo_setup + show_message, then the nested
// simple_demo_trial_loop below animates that demo block's walk.
var simple_demo_block_loop;
function simple_demo_block_loopLoopBegin(simple_demo_block_loopLoopScheduler, snapshot) {
  return async function() {
    TrialHandler.fromSnapshot(snapshot); // update internal variables (.thisN etc) of the loop
    
    // set up handler to look after randomisation of conditions etc
    simple_demo_block_loop = new TrialHandler({
      psychoJS: psychoJS,
      nReps: 1, method: TrialHandler.Method.SEQUENTIAL,
      extraInfo: expInfo, originPath: undefined,
      trialList: 'Resources/PigeonSimpleDemoConditions.xlsx',
      seed: undefined, name: 'simple_demo_block_loop'
    });
    psychoJS.experiment.addLoop(simple_demo_block_loop); // add the loop to the experiment
    currentLoop = simple_demo_block_loop;  // we're now the current loop
    
    // Schedule all the trials in the trialList:
    for (const thisSimple_demo_block_loop of simple_demo_block_loop) {
      snapshot = simple_demo_block_loop.getSnapshot();
      simple_demo_block_loopLoopScheduler.add(importConditions(snapshot));
      simple_demo_block_loopLoopScheduler.add(simple_demo_setupRoutineBegin(snapshot));
      simple_demo_block_loopLoopScheduler.add(simple_demo_setupRoutineEachFrame());
      simple_demo_block_loopLoopScheduler.add(simple_demo_setupRoutineEnd(snapshot));
      simple_demo_block_loopLoopScheduler.add(show_messageRoutineBegin(snapshot));
      simple_demo_block_loopLoopScheduler.add(show_messageRoutineEachFrame());
      simple_demo_block_loopLoopScheduler.add(show_messageRoutineEnd(snapshot));
      const simple_demo_trial_loopLoopScheduler = new Scheduler(psychoJS);
      simple_demo_block_loopLoopScheduler.add(simple_demo_trial_loopLoopBegin(simple_demo_trial_loopLoopScheduler, snapshot));
      simple_demo_block_loopLoopScheduler.add(simple_demo_trial_loopLoopScheduler);
      simple_demo_block_loopLoopScheduler.add(simple_demo_trial_loopLoopEnd);
      simple_demo_block_loopLoopScheduler.add(simple_demo_block_loopLoopEndIteration(simple_demo_block_loopLoopScheduler, snapshot));
    }
    
    return Scheduler.Event.NEXT;
  }
}


// LOOP "simple_demo_trial_loop": nested inside simple_demo_block_loop. nReps: 1000 is a
// generous cap, not a real trial count -- each iteration is one "simple_demo" animation
// step, and the loop self-terminates (simple_demo_trial_loop.finished = true, set inside
// simple_demoRoutineBegin) once Petey reaches an edge or the fixed 50-step demo ends.
var simple_demo_trial_loop;
function simple_demo_trial_loopLoopBegin(simple_demo_trial_loopLoopScheduler, snapshot) {
  return async function() {
    TrialHandler.fromSnapshot(snapshot); // update internal variables (.thisN etc) of the loop
    
    // set up handler to look after randomisation of conditions etc
    simple_demo_trial_loop = new TrialHandler({
      psychoJS: psychoJS,
      nReps: 1000, method: TrialHandler.Method.SEQUENTIAL,
      extraInfo: expInfo, originPath: undefined,
      trialList: undefined,
      seed: undefined, name: 'simple_demo_trial_loop'
    });
    psychoJS.experiment.addLoop(simple_demo_trial_loop); // add the loop to the experiment
    currentLoop = simple_demo_trial_loop;  // we're now the current loop
    
    // Schedule all the trials in the trialList:
    for (const thisSimple_demo_trial_loop of simple_demo_trial_loop) {
      snapshot = simple_demo_trial_loop.getSnapshot();
      simple_demo_trial_loopLoopScheduler.add(importConditions(snapshot));
      simple_demo_trial_loopLoopScheduler.add(simple_demoRoutineBegin(snapshot));
      simple_demo_trial_loopLoopScheduler.add(simple_demoRoutineEachFrame());
      simple_demo_trial_loopLoopScheduler.add(simple_demoRoutineEnd(snapshot));
      simple_demo_trial_loopLoopScheduler.add(simple_demo_trial_loopLoopEndIteration(simple_demo_trial_loopLoopScheduler, snapshot));
    }
    
    return Scheduler.Event.NEXT;
  }
}


async function simple_demo_trial_loopLoopEnd() {
  // terminate loop
  psychoJS.experiment.removeLoop(simple_demo_trial_loop);
  // update the current loop from the ExperimentHandler
  if (psychoJS.experiment._unfinishedLoops.length>0)
    currentLoop = psychoJS.experiment._unfinishedLoops.at(-1);
  else
    currentLoop = psychoJS.experiment;  // so we use addData from the experiment
  return Scheduler.Event.NEXT;
}


function simple_demo_trial_loopLoopEndIteration(scheduler, snapshot) {
  // ------Prepare for next entry------
  return async function () {
    if (typeof snapshot !== 'undefined') {
      // ------Check if user ended loop early------
      if (snapshot.finished) {
        // Check for and save orphaned data
        if (psychoJS.experiment.isEntryEmpty()) {
          psychoJS.experiment.nextEntry(snapshot);
        }
        scheduler.stop();
      }
    return Scheduler.Event.NEXT;
    }
  };
}


async function simple_demo_block_loopLoopEnd() {
  // terminate loop
  psychoJS.experiment.removeLoop(simple_demo_block_loop);
  // update the current loop from the ExperimentHandler
  if (psychoJS.experiment._unfinishedLoops.length>0)
    currentLoop = psychoJS.experiment._unfinishedLoops.at(-1);
  else
    currentLoop = psychoJS.experiment;  // so we use addData from the experiment
  return Scheduler.Event.NEXT;
}


function simple_demo_block_loopLoopEndIteration(scheduler, snapshot) {
  // ------Prepare for next entry------
  return async function () {
    if (typeof snapshot !== 'undefined') {
      // ------Check if user ended loop early------
      if (snapshot.finished) {
        // Check for and save orphaned data
        if (psychoJS.experiment.isEntryEmpty()) {
          psychoJS.experiment.nextEntry(snapshot);
        }
        scheduler.stop();
      }
    return Scheduler.Event.NEXT;
    }
  };
}


// LOOP "status_instruction_loop": 1 pass over PigeonStatusInstructionsConditions.xlsx (the
// coins/steps status-bar walkthrough), one status_instruction_setup + show_message per row.
var status_instruction_loop;
function status_instruction_loopLoopBegin(status_instruction_loopLoopScheduler, snapshot) {
  return async function() {
    TrialHandler.fromSnapshot(snapshot); // update internal variables (.thisN etc) of the loop
    
    // set up handler to look after randomisation of conditions etc
    status_instruction_loop = new TrialHandler({
      psychoJS: psychoJS,
      nReps: 1, method: TrialHandler.Method.SEQUENTIAL,
      extraInfo: expInfo, originPath: undefined,
      trialList: 'Resources/PigeonStatusInstructionsConditions.xlsx',
      seed: undefined, name: 'status_instruction_loop'
    });
    psychoJS.experiment.addLoop(status_instruction_loop); // add the loop to the experiment
    currentLoop = status_instruction_loop;  // we're now the current loop
    
    // Schedule all the trials in the trialList:
    for (const thisStatus_instruction_loop of status_instruction_loop) {
      snapshot = status_instruction_loop.getSnapshot();
      status_instruction_loopLoopScheduler.add(importConditions(snapshot));
      status_instruction_loopLoopScheduler.add(status_instruction_setupRoutineBegin(snapshot));
      status_instruction_loopLoopScheduler.add(status_instruction_setupRoutineEachFrame());
      status_instruction_loopLoopScheduler.add(status_instruction_setupRoutineEnd(snapshot));
      status_instruction_loopLoopScheduler.add(show_messageRoutineBegin(snapshot));
      status_instruction_loopLoopScheduler.add(show_messageRoutineEachFrame());
      status_instruction_loopLoopScheduler.add(show_messageRoutineEnd(snapshot));
      status_instruction_loopLoopScheduler.add(status_instruction_loopLoopEndIteration(status_instruction_loopLoopScheduler, snapshot));
    }
    
    return Scheduler.Event.NEXT;
  }
}


async function status_instruction_loopLoopEnd() {
  // terminate loop
  psychoJS.experiment.removeLoop(status_instruction_loop);
  // update the current loop from the ExperimentHandler
  if (psychoJS.experiment._unfinishedLoops.length>0)
    currentLoop = psychoJS.experiment._unfinishedLoops.at(-1);
  else
    currentLoop = psychoJS.experiment;  // so we use addData from the experiment
  return Scheduler.Event.NEXT;
}


function status_instruction_loopLoopEndIteration(scheduler, snapshot) {
  // ------Prepare for next entry------
  return async function () {
    if (typeof snapshot !== 'undefined') {
      // ------Check if user ended loop early------
      if (snapshot.finished) {
        // Check for and save orphaned data
        if (psychoJS.experiment.isEntryEmpty()) {
          psychoJS.experiment.nextEntry(snapshot);
        }
        scheduler.stop();
      }
    return Scheduler.Event.NEXT;
    }
  };
}


// LOOP "experiment_loop": THE BLOCK LOOP. 1 pass over PigeonTaskConditions.xlsx, one real
// task block per row (start_task loads that row's tc_* columns; see start_taskRoutineBegin
// for the block_type designs). Per block: start_task -> show_message -> instructions_loop
// (block-type-specific instructions) -> trial_loop (the block's trials).
var experiment_loop;
function experiment_loopLoopBegin(experiment_loopLoopScheduler, snapshot) {
  return async function() {
    TrialHandler.fromSnapshot(snapshot); // update internal variables (.thisN etc) of the loop
    
    // set up handler to look after randomisation of conditions etc
    // Block order: the fixed blocks first, in random order, then the change blocks, in random
    // order. TrialHandler takes the rows as an array, run SEQUENTIAL in the order built here.
    const shuffle_pair = (rows) => (Math.random() < 0.5 ? rows : rows.slice().reverse());
    const all_blocks = TrialHandler.importConditions(psychoJS.serverManager, 'Resources/PigeonTaskConditions.xlsx');
    const ordered_blocks = shuffle_pair(all_blocks.filter((row) => !row.tc_changepoint))
      .concat(shuffle_pair(all_blocks.filter((row) => row.tc_changepoint)));
    if (ordered_blocks.length !== 4) {
      throw new Error("PigeonTaskConditions.xlsx must have two fixed and two change blocks.");
    }
    block_order = ordered_blocks.map((row) => row.tc_block_type).join(",");
    expInfo['block_order'] = block_order;
    experiment_loop = new TrialHandler({
      psychoJS: psychoJS,
      nReps: 1, method: TrialHandler.Method.SEQUENTIAL,
      extraInfo: expInfo, originPath: undefined,
      trialList: ordered_blocks,
      seed: undefined, name: 'experiment_loop'
    });
    psychoJS.experiment.addLoop(experiment_loop); // add the loop to the experiment
    currentLoop = experiment_loop;  // we're now the current loop
    
    // Schedule all the trials in the trialList:
    for (const thisExperiment_loop of experiment_loop) {
      snapshot = experiment_loop.getSnapshot();
      experiment_loopLoopScheduler.add(importConditions(snapshot));
      experiment_loopLoopScheduler.add(start_taskRoutineBegin(snapshot));
      experiment_loopLoopScheduler.add(start_taskRoutineEachFrame());
      experiment_loopLoopScheduler.add(start_taskRoutineEnd(snapshot));
      experiment_loopLoopScheduler.add(show_messageRoutineBegin(snapshot));
      experiment_loopLoopScheduler.add(show_messageRoutineEachFrame());
      experiment_loopLoopScheduler.add(show_messageRoutineEnd(snapshot));
      const instructions_loopLoopScheduler = new Scheduler(psychoJS);
      experiment_loopLoopScheduler.add(instructions_loopLoopBegin(instructions_loopLoopScheduler, snapshot));
      experiment_loopLoopScheduler.add(instructions_loopLoopScheduler);
      experiment_loopLoopScheduler.add(instructions_loopLoopEnd);
      const trial_loopLoopScheduler = new Scheduler(psychoJS);
      experiment_loopLoopScheduler.add(trial_loopLoopBegin(trial_loopLoopScheduler, snapshot));
      experiment_loopLoopScheduler.add(trial_loopLoopScheduler);
      experiment_loopLoopScheduler.add(trial_loopLoopEnd);
      experiment_loopLoopScheduler.add(experiment_loopLoopEndIteration(experiment_loopLoopScheduler, snapshot));
    }
    
    return Scheduler.Event.NEXT;
  }
}


// LOOP "instructions_loop": 1 pass over Resources/Pigeon_<fixed|change>_InstructionsConditions.xlsx
// (chosen by start_task's instructions_conditions_file, based on this block's type), one
// setup_instructions_message + show_message per row.
var instructions_loop;
function instructions_loopLoopBegin(instructions_loopLoopScheduler, snapshot) {
  return async function() {
    TrialHandler.fromSnapshot(snapshot); // update internal variables (.thisN etc) of the loop
    
    // set up handler to look after randomisation of conditions etc
    instructions_loop = new TrialHandler({
      psychoJS: psychoJS,
      nReps: 1, method: TrialHandler.Method.SEQUENTIAL,
      extraInfo: expInfo, originPath: undefined,
      trialList: instructions_conditions_file,
      seed: undefined, name: 'instructions_loop'
    });
    psychoJS.experiment.addLoop(instructions_loop); // add the loop to the experiment
    currentLoop = instructions_loop;  // we're now the current loop
    
    // Schedule all the trials in the trialList:
    for (const thisInstructions_loop of instructions_loop) {
      snapshot = instructions_loop.getSnapshot();
      instructions_loopLoopScheduler.add(importConditions(snapshot));
      instructions_loopLoopScheduler.add(setup_instructions_messageRoutineBegin(snapshot));
      instructions_loopLoopScheduler.add(setup_instructions_messageRoutineEachFrame());
      instructions_loopLoopScheduler.add(setup_instructions_messageRoutineEnd(snapshot));
      instructions_loopLoopScheduler.add(show_messageRoutineBegin(snapshot));
      instructions_loopLoopScheduler.add(show_messageRoutineEachFrame());
      instructions_loopLoopScheduler.add(show_messageRoutineEnd(snapshot));
      instructions_loopLoopScheduler.add(instructions_loopLoopEndIteration(instructions_loopLoopScheduler, snapshot));
    }
    
    return Scheduler.Event.NEXT;
  }
}


async function instructions_loopLoopEnd() {
  // terminate loop
  psychoJS.experiment.removeLoop(instructions_loop);
  // update the current loop from the ExperimentHandler
  if (psychoJS.experiment._unfinishedLoops.length>0)
    currentLoop = psychoJS.experiment._unfinishedLoops.at(-1);
  else
    currentLoop = psychoJS.experiment;  // so we use addData from the experiment
  return Scheduler.Event.NEXT;
}


function instructions_loopLoopEndIteration(scheduler, snapshot) {
  // ------Prepare for next entry------
  return async function () {
    if (typeof snapshot !== 'undefined') {
      // ------Check if user ended loop early------
      if (snapshot.finished) {
        // Check for and save orphaned data
        if (psychoJS.experiment.isEntryEmpty()) {
          psychoJS.experiment.nextEntry(snapshot);
        }
        scheduler.stop();
      }
    return Scheduler.Event.NEXT;
    }
  };
}


// LOOP "trial_loop": nested inside experiment_loop, one iteration per trial within the
// current block. nReps: online_trials_count (10000, set by start_task) is a large cap, not
// a real trial count -- trials keep running (each iteration: move_loop, then show_message
// for the between-trial feedback screen) until the block's step/coin budget runs out and
// trial_loop.finished is set (see the block-budget check in otr_code_update, task_run's
// Begin Routine code). method: FULLRANDOM has no effect here since trialList is undefined
// (there is nothing to randomize order over -- each "trial" is generated fresh by task_run,
// not drawn from a per-trial conditions list).
var trial_loop;
function trial_loopLoopBegin(trial_loopLoopScheduler, snapshot) {
  return async function() {
    TrialHandler.fromSnapshot(snapshot); // update internal variables (.thisN etc) of the loop
    
    // set up handler to look after randomisation of conditions etc
    trial_loop = new TrialHandler({
      psychoJS: psychoJS,
      nReps: online_trials_count, method: TrialHandler.Method.FULLRANDOM,
      extraInfo: expInfo, originPath: undefined,
      trialList: undefined,
      seed: undefined, name: 'trial_loop'
    });
    psychoJS.experiment.addLoop(trial_loop); // add the loop to the experiment
    currentLoop = trial_loop;  // we're now the current loop
    
    // Schedule all the trials in the trialList:
    for (const thisTrial_loop of trial_loop) {
      snapshot = trial_loop.getSnapshot();
      trial_loopLoopScheduler.add(importConditions(snapshot));
      const move_loopLoopScheduler = new Scheduler(psychoJS);
      trial_loopLoopScheduler.add(move_loopLoopBegin(move_loopLoopScheduler, snapshot));
      trial_loopLoopScheduler.add(move_loopLoopScheduler);
      trial_loopLoopScheduler.add(move_loopLoopEnd);
      trial_loopLoopScheduler.add(show_messageRoutineBegin(snapshot));
      trial_loopLoopScheduler.add(show_messageRoutineEachFrame());
      trial_loopLoopScheduler.add(show_messageRoutineEnd(snapshot));
      trial_loopLoopScheduler.add(trial_loopLoopEndIteration(trial_loopLoopScheduler, snapshot));
    }
    
    return Scheduler.Event.NEXT;
  }
}


// LOOP "move_loop": nested inside trial_loop, one iteration per animation step of a single
// trial's pigeon walk. nReps: 1000 is a generous cap (comfortably above STEPS_MAX_PER_TRIAL);
// the loop actually ends via move_loop.finished, set in task_runRoutineEnd (otr_code_update)
// on a response, a block-budget exhaustion, or the STEPS_MAX_PER_TRIAL timeout.
var move_loop;
function move_loopLoopBegin(move_loopLoopScheduler, snapshot) {
  return async function() {
    TrialHandler.fromSnapshot(snapshot); // update internal variables (.thisN etc) of the loop
    
    // set up handler to look after randomisation of conditions etc
    move_loop = new TrialHandler({
      psychoJS: psychoJS,
      nReps: 1000, method: TrialHandler.Method.SEQUENTIAL,
      extraInfo: expInfo, originPath: undefined,
      trialList: undefined,
      seed: undefined, name: 'move_loop'
    });
    psychoJS.experiment.addLoop(move_loop); // add the loop to the experiment
    currentLoop = move_loop;  // we're now the current loop
    
    // Schedule all the trials in the trialList:
    for (const thisMove_loop of move_loop) {
      snapshot = move_loop.getSnapshot();
      move_loopLoopScheduler.add(importConditions(snapshot));
      move_loopLoopScheduler.add(task_runRoutineBegin(snapshot));
      move_loopLoopScheduler.add(task_runRoutineEachFrame());
      move_loopLoopScheduler.add(task_runRoutineEnd(snapshot));
      move_loopLoopScheduler.add(move_loopLoopEndIteration(move_loopLoopScheduler, snapshot));
    }
    
    return Scheduler.Event.NEXT;
  }
}


async function move_loopLoopEnd() {
  // terminate loop
  psychoJS.experiment.removeLoop(move_loop);
  // update the current loop from the ExperimentHandler
  if (psychoJS.experiment._unfinishedLoops.length>0)
    currentLoop = psychoJS.experiment._unfinishedLoops.at(-1);
  else
    currentLoop = psychoJS.experiment;  // so we use addData from the experiment
  return Scheduler.Event.NEXT;
}


function move_loopLoopEndIteration(scheduler, snapshot) {
  // ------Prepare for next entry------
  return async function () {
    if (typeof snapshot !== 'undefined') {
      // ------Check if user ended loop early------
      if (snapshot.finished) {
        // Check for and save orphaned data
        if (psychoJS.experiment.isEntryEmpty()) {
          psychoJS.experiment.nextEntry(snapshot);
        }
        scheduler.stop();
      }
    return Scheduler.Event.NEXT;
    }
  };
}


async function trial_loopLoopEnd() {
  // terminate loop
  psychoJS.experiment.removeLoop(trial_loop);
  // update the current loop from the ExperimentHandler
  if (psychoJS.experiment._unfinishedLoops.length>0)
    currentLoop = psychoJS.experiment._unfinishedLoops.at(-1);
  else
    currentLoop = psychoJS.experiment;  // so we use addData from the experiment
  return Scheduler.Event.NEXT;
}


function trial_loopLoopEndIteration(scheduler, snapshot) {
  // ------Prepare for next entry------
  return async function () {
    if (typeof snapshot !== 'undefined') {
      // ------Check if user ended loop early------
      if (snapshot.finished) {
        // Check for and save orphaned data
        if (psychoJS.experiment.isEntryEmpty()) {
          psychoJS.experiment.nextEntry(snapshot);
        }
        scheduler.stop();
      } else {
        psychoJS.experiment.nextEntry(snapshot);
      }
    return Scheduler.Event.NEXT;
    }
  };
}


async function experiment_loopLoopEnd() {
  // terminate loop
  psychoJS.experiment.removeLoop(experiment_loop);
  // update the current loop from the ExperimentHandler
  if (psychoJS.experiment._unfinishedLoops.length>0)
    currentLoop = psychoJS.experiment._unfinishedLoops.at(-1);
  else
    currentLoop = psychoJS.experiment;  // so we use addData from the experiment
  return Scheduler.Event.NEXT;
}


function experiment_loopLoopEndIteration(scheduler, snapshot) {
  // ------Prepare for next entry------
  return async function () {
    if (typeof snapshot !== 'undefined') {
      // ------Check if user ended loop early------
      if (snapshot.finished) {
        // Check for and save orphaned data
        if (psychoJS.experiment.isEntryEmpty()) {
          psychoJS.experiment.nextEntry(snapshot);
        }
        scheduler.stop();
      } else {
        psychoJS.experiment.nextEntry(snapshot);
      }
    return Scheduler.Event.NEXT;
    }
  };
}


// ROUTINE PAIR "general_instructions_setup" + "show_message" (looped once per row of
// PigeonGeneralInstructionsConditions.xlsx by general_instructions_loop): a static
// text/image screen shown before any task blocks, with gic_* columns controlling whether
// the pigeon/seeds are shown alongside the instruction text (gic_message).
var general_instructions_setupComponents;
function general_instructions_setupRoutineBegin(snapshot) {
  return async function () {
    TrialHandler.fromSnapshot(snapshot); // ensure that .thisN vals are up to date
    
    //--- Prepare to start Routine 'general_instructions_setup' ---
    t = 0;
    general_instructions_setupClock.reset(); // clock
    frameN = -1;
    continueRoutine = true; // until we're told otherwise
    // update component parameters for each repeat
    // Run 'Begin Routine' code from gis_code_setup
    status_show = false;
    box_show = false;
    pigeon_show = gic_pigeon_show;
    seeds_show = gic_seeds_show;
    message_string = gic_message;
    
    // keep track of which components have finished
    general_instructions_setupComponents = [];
    
    for (const thisComponent of general_instructions_setupComponents)
      if ('status' in thisComponent)
        thisComponent.status = PsychoJS.Status.NOT_STARTED;
    return Scheduler.Event.NEXT;
  }
}


function general_instructions_setupRoutineEachFrame() {
  return async function () {
    //--- Loop for each frame of Routine 'general_instructions_setup' ---
    // get current time
    t = general_instructions_setupClock.getTime();
    frameN = frameN + 1;// number of completed frames (so 0 is the first frame)
    // update/draw components on each frame
    // check for quit (typically the Esc key)
    if (psychoJS.experiment.experimentEnded || psychoJS.eventManager.getKeys({keyList:['escape']}).length > 0) {
      return quitPsychoJS('The [Escape] key was pressed. Goodbye!', false);
    }
    
    // check if the Routine should terminate
    if (!continueRoutine) {  // a component has requested a forced-end of Routine
      return Scheduler.Event.NEXT;
    }
    
    continueRoutine = false;  // reverts to True if at least one component still running
    for (const thisComponent of general_instructions_setupComponents)
      if ('status' in thisComponent && thisComponent.status !== PsychoJS.Status.FINISHED) {
        continueRoutine = true;
        break;
      }
    
    // refresh the screen if continuing
    if (continueRoutine) {
      return Scheduler.Event.FLIP_REPEAT;
    } else {
      return Scheduler.Event.NEXT;
    }
  };
}


function general_instructions_setupRoutineEnd(snapshot) {
  return async function () {
    //--- Ending Routine 'general_instructions_setup' ---
    for (const thisComponent of general_instructions_setupComponents) {
      if (typeof thisComponent.setAutoDraw === 'function') {
        thisComponent.setAutoDraw(false);
      }
    }
    // the Routine "general_instructions_setup" was not non-slip safe, so reset the non-slip timer
    routineTimer.reset();
    
    // Routines running outside a loop should always advance the datafile row
    if (currentLoop === psychoJS.experiment) {
      psychoJS.experiment.nextEntry(snapshot);
    }
    return Scheduler.Event.NEXT;
  }
}


// ROUTINE "show_message": the generic "wait for a keypress on a message screen" routine,
// reused after every instructions/setup routine and after every block/trial-loop
// (waits on space/arrows, ends on any of them). Draws from the *current* values of the
// shared display globals (message_string, instruction_string, coins_/steps_ bar state,
// pigeon_shown_x, env_img, ...) set by whichever routine ran immediately before it, plus
// the show/hide flags (status_show, pigeon_show, seeds_show, box_show, message_show,
// instruction_show) that gate which of its components are actually drawn.
var _sm_kbd_continue_allKeys;
var show_messageComponents;
function show_messageRoutineBegin(snapshot) {
  return async function () {
    TrialHandler.fromSnapshot(snapshot); // ensure that .thisN vals are up to date
    
    //--- Prepare to start Routine 'show_message' ---
    t = 0;
    show_messageClock.reset(); // clock
    frameN = -1;
    continueRoutine = true; // until we're told otherwise
    // update component parameters for each repeat
    sm_kbd_continue.keys = undefined;
    sm_kbd_continue.rt = undefined;
    _sm_kbd_continue_allKeys = [];
    // Run 'Begin Routine' code from sm_code_update
    sm_kbd_continue.clearEvents();
    
    sm_polygon_box.setPos([box_x, box_y]);
    sm_polygon_box.setSize([box_width, box_height]);
    sm_polygon_abscissa.setPos([ORIGIN_X, ABSCISSA_Y]);
    sm_polygon_abscissa.setSize([ABSCISSA_WIDTH, LINE_HEIGHT]);
    sm_polygon_ordinate.setPos([ORIGIN_X, ORDINATE_Y]);
    sm_polygon_ordinate.setSize([ORDINATE_WIDTH, ORDINATE_HEIGHT]);
    sm_polygon_petey_midpoint.setPos([pigeon_shown_x, ORDINATE_Y]);
    sm_polygon_petey_midpoint.setSize([(ORDINATE_WIDTH * 0.9), ORDINATE_HEIGHT]);
    sm_image_right_seeds.setSize([(SEEDS_SCALE * SEEDS_WIDTH), (SEEDS_SCALE * SEEDS_HEIGHT)]);
    sm_image_left_seeds.setSize([(SEEDS_SCALE * SEEDS_WIDTH), (SEEDS_SCALE * SEEDS_HEIGHT)]);
    sm_image_petey.setPos([pigeon_shown_x, ORIGIN_Y]);
    sm_image_petey.setSize([pigeon_flip, 0.1]);
    sm_image_env.setImage(env_img);
    sm_polygon_coin_bar.setPos([COINS_BAR_X, coins_bar_center]);
    sm_polygon_coin_bar.setSize([STATUS_BAR_WIDTH, coins_bar_height]);
    sm_polygon_steps_bar.setPos([STEPS_BAR_X, steps_bar_center]);
    sm_polygon_steps_bar.setSize([STATUS_BAR_WIDTH, steps_bar_height]);
    sm_polygon_status_bar_apex.setPos([ORIGIN_X, STATUS_BAR_APEX_Y]);
    sm_polygon_status_bar_apex.setSize([STATUS_BAR_BRACKET_WIDTH, LINE_HEIGHT]);
    sm_polygon_status_bar_base.setPos([ORIGIN_X, STATUS_BAR_BASE_Y]);
    sm_polygon_status_bar_base.setSize([STATUS_BAR_BRACKET_WIDTH, LINE_HEIGHT]);
    sm_text_coins.setText(coins_text);
    sm_text_coins_properties.setText(coins_string);
    sm_text_steps.setText(steps_text);
    sm_text_steps_label.setText(steps_label);
    sm_text_steps_properties.setText(steps_string);
    sm_text_message.setText(message_string);
    sm_text_instruction.setText(CONTINUE_STRING);
    // keep track of which components have finished
    show_messageComponents = [];
    show_messageComponents.push(sm_kbd_continue);
    show_messageComponents.push(sm_polygon_box);
    show_messageComponents.push(sm_polygon_abscissa);
    show_messageComponents.push(sm_polygon_ordinate);
    show_messageComponents.push(sm_polygon_petey_midpoint);
    show_messageComponents.push(sm_image_right_seeds);
    show_messageComponents.push(sm_image_left_seeds);
    show_messageComponents.push(sm_image_petey);
    show_messageComponents.push(sm_image_env);
    show_messageComponents.push(sm_polygon_coin_bar);
    show_messageComponents.push(sm_polygon_steps_bar);
    show_messageComponents.push(sm_polygon_status_bar_apex);
    show_messageComponents.push(sm_polygon_status_bar_base);
    show_messageComponents.push(sm_text_coins);
    show_messageComponents.push(sm_text_coins_label);
    show_messageComponents.push(sm_text_coins_properties);
    show_messageComponents.push(sm_text_steps);
    show_messageComponents.push(sm_text_steps_label);
    show_messageComponents.push(sm_text_steps_properties);
    show_messageComponents.push(sm_text_message);
    show_messageComponents.push(sm_text_instruction);
    
    for (const thisComponent of show_messageComponents)
      if ('status' in thisComponent)
        thisComponent.status = PsychoJS.Status.NOT_STARTED;
    return Scheduler.Event.NEXT;
  }
}


function show_messageRoutineEachFrame() {
  return async function () {
    //--- Loop for each frame of Routine 'show_message' ---
    // get current time
    t = show_messageClock.getTime();
    frameN = frameN + 1;// number of completed frames (so 0 is the first frame)
    // update/draw components on each frame
    
    // *sm_kbd_continue* updates
    if (t >= 0.0 && sm_kbd_continue.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sm_kbd_continue.tStart = t;  // (not accounting for frame time here)
      sm_kbd_continue.frameNStart = frameN;  // exact frame index
      
      // keyboard checking is just starting
      psychoJS.window.callOnFlip(function() { sm_kbd_continue.clock.reset(); });  // t=0 on next screen flip
      psychoJS.window.callOnFlip(function() { sm_kbd_continue.start(); }); // start on screen flip
      psychoJS.window.callOnFlip(function() { sm_kbd_continue.clearEvents(); });
    }

    if (sm_kbd_continue.status === PsychoJS.Status.STARTED) {
      let theseKeys = sm_kbd_continue.getKeys({keyList: ['space', 'up', 'down', 'left', 'right'], waitRelease: false});
      _sm_kbd_continue_allKeys = _sm_kbd_continue_allKeys.concat(theseKeys);
      if (_sm_kbd_continue_allKeys.length > 0) {
        sm_kbd_continue.keys = _sm_kbd_continue_allKeys[_sm_kbd_continue_allKeys.length - 1].name;  // just the last key pressed
        sm_kbd_continue.rt = _sm_kbd_continue_allKeys[_sm_kbd_continue_allKeys.length - 1].rt;
        // a response ends the routine
        continueRoutine = false;
      }
    }
    
    
    // *sm_polygon_box* updates
    if ((box_show) && sm_polygon_box.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sm_polygon_box.tStart = t;  // (not accounting for frame time here)
      sm_polygon_box.frameNStart = frameN;  // exact frame index
      
      sm_polygon_box.setAutoDraw(true);
    }

    
    // *sm_polygon_abscissa* updates
    if ((pigeon_show) && sm_polygon_abscissa.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sm_polygon_abscissa.tStart = t;  // (not accounting for frame time here)
      sm_polygon_abscissa.frameNStart = frameN;  // exact frame index
      
      sm_polygon_abscissa.setAutoDraw(true);
    }

    
    // *sm_polygon_ordinate* updates
    if ((status_show) && sm_polygon_ordinate.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sm_polygon_ordinate.tStart = t;  // (not accounting for frame time here)
      sm_polygon_ordinate.frameNStart = frameN;  // exact frame index
      
      sm_polygon_ordinate.setAutoDraw(true);
    }

    
    // *sm_polygon_petey_midpoint* updates
    if ((status_show) && sm_polygon_petey_midpoint.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sm_polygon_petey_midpoint.tStart = t;  // (not accounting for frame time here)
      sm_polygon_petey_midpoint.frameNStart = frameN;  // exact frame index
      
      sm_polygon_petey_midpoint.setAutoDraw(true);
    }

    
    // *sm_image_right_seeds* updates
    if ((seeds_show) && sm_image_right_seeds.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sm_image_right_seeds.tStart = t;  // (not accounting for frame time here)
      sm_image_right_seeds.frameNStart = frameN;  // exact frame index
      
      sm_image_right_seeds.setAutoDraw(true);
    }

    
    // *sm_image_left_seeds* updates
    if ((seeds_show) && sm_image_left_seeds.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sm_image_left_seeds.tStart = t;  // (not accounting for frame time here)
      sm_image_left_seeds.frameNStart = frameN;  // exact frame index
      
      sm_image_left_seeds.setAutoDraw(true);
    }

    
    // *sm_image_petey* updates
    if ((pigeon_show) && sm_image_petey.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sm_image_petey.tStart = t;  // (not accounting for frame time here)
      sm_image_petey.frameNStart = frameN;  // exact frame index
      
      sm_image_petey.setAutoDraw(true);
    }

    
    // *sm_image_env* updates
    if ((seeds_show) && sm_image_env.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sm_image_env.tStart = t;  // (not accounting for frame time here)
      sm_image_env.frameNStart = frameN;  // exact frame index
      
      sm_image_env.setAutoDraw(true);
    }

    
    // *sm_polygon_coin_bar* updates
    if ((status_show) && sm_polygon_coin_bar.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sm_polygon_coin_bar.tStart = t;  // (not accounting for frame time here)
      sm_polygon_coin_bar.frameNStart = frameN;  // exact frame index
      
      sm_polygon_coin_bar.setAutoDraw(true);
    }

    
    // *sm_polygon_steps_bar* updates
    if ((status_show) && sm_polygon_steps_bar.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sm_polygon_steps_bar.tStart = t;  // (not accounting for frame time here)
      sm_polygon_steps_bar.frameNStart = frameN;  // exact frame index
      
      sm_polygon_steps_bar.setAutoDraw(true);
    }

    
    // *sm_polygon_status_bar_apex* updates
    if ((status_show) && sm_polygon_status_bar_apex.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sm_polygon_status_bar_apex.tStart = t;  // (not accounting for frame time here)
      sm_polygon_status_bar_apex.frameNStart = frameN;  // exact frame index
      
      sm_polygon_status_bar_apex.setAutoDraw(true);
    }

    
    // *sm_polygon_status_bar_base* updates
    if ((status_show) && sm_polygon_status_bar_base.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sm_polygon_status_bar_base.tStart = t;  // (not accounting for frame time here)
      sm_polygon_status_bar_base.frameNStart = frameN;  // exact frame index
      
      sm_polygon_status_bar_base.setAutoDraw(true);
    }

    
    // *sm_text_coins* updates
    if ((status_show) && sm_text_coins.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sm_text_coins.tStart = t;  // (not accounting for frame time here)
      sm_text_coins.frameNStart = frameN;  // exact frame index
      
      sm_text_coins.setAutoDraw(true);
    }

    
    // *sm_text_coins_label* updates
    if ((status_show) && sm_text_coins_label.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sm_text_coins_label.tStart = t;  // (not accounting for frame time here)
      sm_text_coins_label.frameNStart = frameN;  // exact frame index
      
      sm_text_coins_label.setAutoDraw(true);
    }

    
    // *sm_text_coins_properties* updates
    if ((status_show) && sm_text_coins_properties.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sm_text_coins_properties.tStart = t;  // (not accounting for frame time here)
      sm_text_coins_properties.frameNStart = frameN;  // exact frame index
      
      sm_text_coins_properties.setAutoDraw(true);
    }

    
    // *sm_text_steps* updates
    if ((status_show) && sm_text_steps.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sm_text_steps.tStart = t;  // (not accounting for frame time here)
      sm_text_steps.frameNStart = frameN;  // exact frame index
      
      sm_text_steps.setAutoDraw(true);
    }

    
    // *sm_text_steps_label* updates
    if ((status_show) && sm_text_steps_label.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sm_text_steps_label.tStart = t;  // (not accounting for frame time here)
      sm_text_steps_label.frameNStart = frameN;  // exact frame index
      
      sm_text_steps_label.setAutoDraw(true);
    }

    
    // *sm_text_steps_properties* updates
    if ((status_show) && sm_text_steps_properties.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sm_text_steps_properties.tStart = t;  // (not accounting for frame time here)
      sm_text_steps_properties.frameNStart = frameN;  // exact frame index
      
      sm_text_steps_properties.setAutoDraw(true);
    }

    
    // *sm_text_message* updates
    if ((message_show) && sm_text_message.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sm_text_message.tStart = t;  // (not accounting for frame time here)
      sm_text_message.frameNStart = frameN;  // exact frame index
      
      sm_text_message.setAutoDraw(true);
    }

    
    // *sm_text_instruction* updates
    if ((instruction_show) && sm_text_instruction.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sm_text_instruction.tStart = t;  // (not accounting for frame time here)
      sm_text_instruction.frameNStart = frameN;  // exact frame index
      
      sm_text_instruction.setAutoDraw(true);
    }

    // check for quit (typically the Esc key)
    if (psychoJS.experiment.experimentEnded || psychoJS.eventManager.getKeys({keyList:['escape']}).length > 0) {
      return quitPsychoJS('The [Escape] key was pressed. Goodbye!', false);
    }
    
    // check if the Routine should terminate
    if (!continueRoutine) {  // a component has requested a forced-end of Routine
      return Scheduler.Event.NEXT;
    }
    
    continueRoutine = false;  // reverts to True if at least one component still running
    for (const thisComponent of show_messageComponents)
      if ('status' in thisComponent && thisComponent.status !== PsychoJS.Status.FINISHED) {
        continueRoutine = true;
        break;
      }
    
    // refresh the screen if continuing
    if (continueRoutine) {
      return Scheduler.Event.FLIP_REPEAT;
    } else {
      return Scheduler.Event.NEXT;
    }
  };
}


function show_messageRoutineEnd(snapshot) {
  return async function () {
    //--- Ending Routine 'show_message' ---
    for (const thisComponent of show_messageComponents) {
      if (typeof thisComponent.setAutoDraw === 'function') {
        thisComponent.setAutoDraw(false);
      }
    }
    sm_kbd_continue.stop();
    // Run 'End Routine' code from sm_code_update
    // Every show_message is followed (per trial_loop's scheduling) by another task_run call;
    // setting trial_start here is what tells that next task_run to initialize a fresh trial
    // rather than continue animating the one that just ended.
    trial_start = true;
    
    // the Routine "show_message" was not non-slip safe, so reset the non-slip timer
    routineTimer.reset();
    
    // Routines running outside a loop should always advance the datafile row
    if (currentLoop === psychoJS.experiment) {
      psychoJS.experiment.nextEntry(snapshot);
    }
    return Scheduler.Event.NEXT;
  }
}


// ROUTINE PAIR "simple_demo_setup" + "show_message" + nested "simple_demo" loop
// (simple_demo_block_loop, looped once per row of PigeonSimpleDemoConditions.xlsx; each
// block's own simple_demo_trial_loop then repeats the "simple_demo" routine up to 1000
// times). This is the practice/demo phase: Petey walks automatically (no response
// required) so the participant can watch the SNR play out. sdc_step_mean===0 with
// sdc_step_std!==0 demos a pure random walk (no drift) that self-terminates after exactly
// 50 steps (see simple_demoRoutineBegin); otherwise the walk runs until Petey reaches an
// edge.
var demo_start;
var step_mean;
var step_std;
var simple_demo_setupComponents;
function simple_demo_setupRoutineBegin(snapshot) {
  return async function () {
    TrialHandler.fromSnapshot(snapshot); // ensure that .thisN vals are up to date
    
    //--- Prepare to start Routine 'simple_demo_setup' ---
    t = 0;
    simple_demo_setupClock.reset(); // clock
    frameN = -1;
    continueRoutine = true; // until we're told otherwise
    // update component parameters for each repeat
    // Run 'Begin Routine' code from sds_code_setup
    seeds_show = true;
    pigeon_show = true;
    status_show = false;
    box_show = false;
    demo_start = true;
    steps_count = 0;
    message_string = sdc_message;
    step_mean = sdc_step_mean;
    step_std = sdc_step_std;
    SEEDS_SCALE = sdc_seeds_scale;
    if ((sdc_img_file !== null)) {
        env_img = ("Resources/" + sdc_img_file);
    } else {
        env_img = high_env_img;
    }
    
    // keep track of which components have finished
    simple_demo_setupComponents = [];
    
    for (const thisComponent of simple_demo_setupComponents)
      if ('status' in thisComponent)
        thisComponent.status = PsychoJS.Status.NOT_STARTED;
    return Scheduler.Event.NEXT;
  }
}


function simple_demo_setupRoutineEachFrame() {
  return async function () {
    //--- Loop for each frame of Routine 'simple_demo_setup' ---
    // get current time
    t = simple_demo_setupClock.getTime();
    frameN = frameN + 1;// number of completed frames (so 0 is the first frame)
    // update/draw components on each frame
    // check for quit (typically the Esc key)
    if (psychoJS.experiment.experimentEnded || psychoJS.eventManager.getKeys({keyList:['escape']}).length > 0) {
      return quitPsychoJS('The [Escape] key was pressed. Goodbye!', false);
    }
    
    // check if the Routine should terminate
    if (!continueRoutine) {  // a component has requested a forced-end of Routine
      return Scheduler.Event.NEXT;
    }
    
    continueRoutine = false;  // reverts to True if at least one component still running
    for (const thisComponent of simple_demo_setupComponents)
      if ('status' in thisComponent && thisComponent.status !== PsychoJS.Status.FINISHED) {
        continueRoutine = true;
        break;
      }
    
    // refresh the screen if continuing
    if (continueRoutine) {
      return Scheduler.Event.FLIP_REPEAT;
    } else {
      return Scheduler.Event.NEXT;
    }
  };
}


function simple_demo_setupRoutineEnd(snapshot) {
  return async function () {
    //--- Ending Routine 'simple_demo_setup' ---
    for (const thisComponent of simple_demo_setupComponents) {
      if (typeof thisComponent.setAutoDraw === 'function') {
        thisComponent.setAutoDraw(false);
      }
    }
    // the Routine "simple_demo_setup" was not non-slip safe, so reset the non-slip timer
    routineTimer.reset();
    
    // Routines running outside a loop should always advance the datafile row
    if (currentLoop === psychoJS.experiment) {
      psychoJS.experiment.nextEntry(snapshot);
    }
    return Scheduler.Event.NEXT;
  }
}


var simple_demoComponents;
function simple_demoRoutineBegin(snapshot) {
  return async function () {
    TrialHandler.fromSnapshot(snapshot); // ensure that .thisN vals are up to date
    
    //--- Prepare to start Routine 'simple_demo' ---
    t = 0;
    simple_demoClock.reset(); // clock
    frameN = -1;
    continueRoutine = true; // until we're told otherwise
    // update component parameters for each repeat
    // Run 'Begin Routine' code from sd_code_update
    // First call for this demo block (demo_start, set by simple_demo_setup): reset Petey to
    // center and pick a random left/right sign for this demo's drift, mirroring the real
    // task's per-trial direction draw in otr_code_update. Every later call is one animation
    // step: advance the walk and stop the simple_demo_trial_loop once Petey reaches an edge,
    // or -- for the no-drift demo (step_mean === 0) -- after a fixed 50 steps, since a
    // zero-mean walk has no edge to reach and would otherwise run indefinitely.
    if (demo_start) {
        pigeon_flip = 0.1;
        pigeon_true_x = 0;
        pigeon_shown_x = pigeon_true_x;
        if ((util.randint(0, 2) === 0)) {
            step_mean_val = ((- 1) * Math.abs(step_mean));
        } else {
            step_mean_val = Math.abs(step_mean);
        }
        step_std_val = step_std;
        demo_start = false;
    } else {
        if (((step_mean === 0) && (steps_count === 50))) {
            simple_demo_trial_loop.finished = true;
        }
        if (((pigeon_true_x > (- EDGE_DISTANCE)) && (pigeon_true_x < EDGE_DISTANCE))) {
            move_pigeon(step_mean_val, step_std_val);
            steps_count += 1;
        } else {
            simple_demo_trial_loop.finished = true;
        }
    }
    
    sd_polygon_abscissa.setPos([ORIGIN_X, ABSCISSA_Y]);
    sd_polygon_abscissa.setSize([(EDGE_DISTANCE * 2), LINE_HEIGHT]);
    sd_image_left_seeds.setSize([(SEEDS_SCALE * SEEDS_WIDTH), (SEEDS_SCALE * SEEDS_HEIGHT)]);
    sd_image_right_seeds.setSize([(SEEDS_SCALE * SEEDS_WIDTH), (SEEDS_SCALE * SEEDS_HEIGHT)]);
    sd_image_pigeon.setPos([pigeon_shown_x, ORIGIN_Y]);
    sd_image_pigeon.setSize([pigeon_flip, 0.1]);
    sm_env_img.setImage(env_img);
    // keep track of which components have finished
    simple_demoComponents = [];
    simple_demoComponents.push(sd_polygon_abscissa);
    simple_demoComponents.push(sd_image_left_seeds);
    simple_demoComponents.push(sd_image_right_seeds);
    simple_demoComponents.push(sd_image_pigeon);
    simple_demoComponents.push(sm_env_img);
    
    for (const thisComponent of simple_demoComponents)
      if ('status' in thisComponent)
        thisComponent.status = PsychoJS.Status.NOT_STARTED;
    return Scheduler.Event.NEXT;
  }
}


var frameRemains;
function simple_demoRoutineEachFrame() {
  return async function () {
    //--- Loop for each frame of Routine 'simple_demo' ---
    // get current time
    t = simple_demoClock.getTime();
    frameN = frameN + 1;// number of completed frames (so 0 is the first frame)
    // update/draw components on each frame
    
    // *sd_polygon_abscissa* updates
    if (t >= 0.0 && sd_polygon_abscissa.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sd_polygon_abscissa.tStart = t;  // (not accounting for frame time here)
      sd_polygon_abscissa.frameNStart = frameN;  // exact frame index
      
      sd_polygon_abscissa.setAutoDraw(true);
    }

    frameRemains = 0.0 + UPDATE_INTERVAL - psychoJS.window.monitorFramePeriod * 0.75;  // most of one frame period left
    if (sd_polygon_abscissa.status === PsychoJS.Status.STARTED && t >= frameRemains) {
      sd_polygon_abscissa.setAutoDraw(false);
    }
    
    // *sd_image_left_seeds* updates
    if (t >= 0.0 && sd_image_left_seeds.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sd_image_left_seeds.tStart = t;  // (not accounting for frame time here)
      sd_image_left_seeds.frameNStart = frameN;  // exact frame index
      
      sd_image_left_seeds.setAutoDraw(true);
    }

    frameRemains = 0.0 + UPDATE_INTERVAL - psychoJS.window.monitorFramePeriod * 0.75;  // most of one frame period left
    if (sd_image_left_seeds.status === PsychoJS.Status.STARTED && t >= frameRemains) {
      sd_image_left_seeds.setAutoDraw(false);
    }
    
    // *sd_image_right_seeds* updates
    if (t >= 0.0 && sd_image_right_seeds.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sd_image_right_seeds.tStart = t;  // (not accounting for frame time here)
      sd_image_right_seeds.frameNStart = frameN;  // exact frame index
      
      sd_image_right_seeds.setAutoDraw(true);
    }

    frameRemains = 0.0 + UPDATE_INTERVAL - psychoJS.window.monitorFramePeriod * 0.75;  // most of one frame period left
    if (sd_image_right_seeds.status === PsychoJS.Status.STARTED && t >= frameRemains) {
      sd_image_right_seeds.setAutoDraw(false);
    }
    
    // *sd_image_pigeon* updates
    if (t >= 0.0 && sd_image_pigeon.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sd_image_pigeon.tStart = t;  // (not accounting for frame time here)
      sd_image_pigeon.frameNStart = frameN;  // exact frame index
      
      sd_image_pigeon.setAutoDraw(true);
    }

    frameRemains = 0.0 + UPDATE_INTERVAL - psychoJS.window.monitorFramePeriod * 0.75;  // most of one frame period left
    if (sd_image_pigeon.status === PsychoJS.Status.STARTED && t >= frameRemains) {
      sd_image_pigeon.setAutoDraw(false);
    }
    
    // *sm_env_img* updates
    if (t >= 0.0 && sm_env_img.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sm_env_img.tStart = t;  // (not accounting for frame time here)
      sm_env_img.frameNStart = frameN;  // exact frame index
      
      sm_env_img.setAutoDraw(true);
    }

    frameRemains = 0.0 + UPDATE_INTERVAL - psychoJS.window.monitorFramePeriod * 0.75;  // most of one frame period left
    if (sm_env_img.status === PsychoJS.Status.STARTED && t >= frameRemains) {
      sm_env_img.setAutoDraw(false);
    }
    // check for quit (typically the Esc key)
    if (psychoJS.experiment.experimentEnded || psychoJS.eventManager.getKeys({keyList:['escape']}).length > 0) {
      return quitPsychoJS('The [Escape] key was pressed. Goodbye!', false);
    }
    
    // check if the Routine should terminate
    if (!continueRoutine) {  // a component has requested a forced-end of Routine
      return Scheduler.Event.NEXT;
    }
    
    continueRoutine = false;  // reverts to True if at least one component still running
    for (const thisComponent of simple_demoComponents)
      if ('status' in thisComponent && thisComponent.status !== PsychoJS.Status.FINISHED) {
        continueRoutine = true;
        break;
      }
    
    // refresh the screen if continuing
    if (continueRoutine) {
      return Scheduler.Event.FLIP_REPEAT;
    } else {
      return Scheduler.Event.NEXT;
    }
  };
}


function simple_demoRoutineEnd(snapshot) {
  return async function () {
    //--- Ending Routine 'simple_demo' ---
    for (const thisComponent of simple_demoComponents) {
      if (typeof thisComponent.setAutoDraw === 'function') {
        thisComponent.setAutoDraw(false);
      }
    }
    // Run 'End Routine' code from sd_code_update
    // Reset the step counter used by the step_mean===0 timeout check above so the next demo
    // block (a fresh row of simple_demo_block_loop) starts its own 50-step countdown.
    if (simple_demo_trial_loop.finished) {
        steps_count = 0;
    }
    
    // the Routine "simple_demo" was not non-slip safe, so reset the non-slip timer
    routineTimer.reset();
    
    // Routines running outside a loop should always advance the datafile row
    if (currentLoop === psychoJS.experiment) {
      psychoJS.experiment.nextEntry(snapshot);
    }
    return Scheduler.Event.NEXT;
  }
}


// ROUTINE PAIR "status_instruction_setup" + "show_message" (status_instruction_loop, once
// per row of PigeonStatusInstructionsConditions.xlsx): explains the coins/steps status bars
// before the real task blocks start, using a fixed demo steps_count/coins_count state
// (steps_count is incremented by exactly 1 below purely to make the steps bar render
// non-empty for the screenshot-like instructional display, not as a real task step).
var status_instruction_setupComponents;
function status_instruction_setupRoutineBegin(snapshot) {
  return async function () {
    TrialHandler.fromSnapshot(snapshot); // ensure that .thisN vals are up to date
    
    //--- Prepare to start Routine 'status_instruction_setup' ---
    t = 0;
    status_instruction_setupClock.reset(); // clock
    frameN = -1;
    continueRoutine = true; // until we're told otherwise
    // update component parameters for each repeat
    // Run 'Begin Routine' code from sis_code_setup
    status_show = true;
    pigeon_show = true;
    seeds_show = true;
    pigeon_flip = 0.1;
    pigeon_true_x = 0;
    pigeon_shown_x = pigeon_true_x;
    box_show = sic_box_show;
    box_width = sic_box_width;
    box_height = sic_box_height;
    box_x = sic_box_x;
    box_y = sic_box_y;
    message_string = sic_message;
    SEEDS_SCALE = sic_seeds_scale;
    if ((sic_img_file !== null)) {
        env_img = ("Resources/" + sic_img_file);
    } else {
        env_img = high_env_img;
    }
    steps_label = "Steps Remaining";
    steps_text = (steps_max - steps_count).toString();
    coins_text = coins_count.toString();
    steps_count += 1;
    update_status(true, true, true, false);
    
    // keep track of which components have finished
    status_instruction_setupComponents = [];
    
    for (const thisComponent of status_instruction_setupComponents)
      if ('status' in thisComponent)
        thisComponent.status = PsychoJS.Status.NOT_STARTED;
    return Scheduler.Event.NEXT;
  }
}


function status_instruction_setupRoutineEachFrame() {
  return async function () {
    //--- Loop for each frame of Routine 'status_instruction_setup' ---
    // get current time
    t = status_instruction_setupClock.getTime();
    frameN = frameN + 1;// number of completed frames (so 0 is the first frame)
    // update/draw components on each frame
    // check for quit (typically the Esc key)
    if (psychoJS.experiment.experimentEnded || psychoJS.eventManager.getKeys({keyList:['escape']}).length > 0) {
      return quitPsychoJS('The [Escape] key was pressed. Goodbye!', false);
    }
    
    // check if the Routine should terminate
    if (!continueRoutine) {  // a component has requested a forced-end of Routine
      return Scheduler.Event.NEXT;
    }
    
    continueRoutine = false;  // reverts to True if at least one component still running
    for (const thisComponent of status_instruction_setupComponents)
      if ('status' in thisComponent && thisComponent.status !== PsychoJS.Status.FINISHED) {
        continueRoutine = true;
        break;
      }
    
    // refresh the screen if continuing
    if (continueRoutine) {
      return Scheduler.Event.FLIP_REPEAT;
    } else {
      return Scheduler.Event.NEXT;
    }
  };
}


function status_instruction_setupRoutineEnd(snapshot) {
  return async function () {
    //--- Ending Routine 'status_instruction_setup' ---
    for (const thisComponent of status_instruction_setupComponents) {
      if (typeof thisComponent.setAutoDraw === 'function') {
        thisComponent.setAutoDraw(false);
      }
    }
    // the Routine "status_instruction_setup" was not non-slip safe, so reset the non-slip timer
    routineTimer.reset();
    
    // Routines running outside a loop should always advance the datafile row
    if (currentLoop === psychoJS.experiment) {
      psychoJS.experiment.nextEntry(snapshot);
    }
    return Scheduler.Event.NEXT;
  }
}


// ROUTINE "start_task" (experiment_loop, once per row of PigeonTaskConditions.xlsx, i.e.
// once per block): resets all per-block state from that row's tc_* columns and clears the
// running RT_block/switch_occurred bookkeeping used by task_run. This is the routine
// that decides block_type / step_mean / step_std / steps_max / changepoint for everything
// that follows (instructions_loop, then trial_loop -> move_loop -> task_run) until the next
// block's start_task runs.
var _pj;
var RT_block;
var block_timeout_count;
var switch_occurred;
var block_type;
var instructions_type;
var env_text;
var instructions_conditions_file;
var online_trials_count;
var start_taskComponents;
function start_taskRoutineBegin(snapshot) {
  return async function () {
    TrialHandler.fromSnapshot(snapshot); // ensure that .thisN vals are up to date
    
    //--- Prepare to start Routine 'start_task' ---
    t = 0;
    start_taskClock.reset(); // clock
    frameN = -1;
    continueRoutine = true; // until we're told otherwise
    // update component parameters for each repeat
    // Run 'Begin Routine' code from st_code_setup
    var _pj;
    function _pj_snippets(container) {
        function in_es6(left, right) {
            if (((right instanceof Array) || ((typeof right) === "string"))) {
                return (right.indexOf(left) > (- 1));
            } else {
                if (((right instanceof Map) || (right instanceof Set) || (right instanceof WeakMap) || (right instanceof WeakSet))) {
                    return right.has(left);
                } else {
                    return (left in right);
                }
            }
        }
        container["in_es6"] = in_es6;
        return container;
    }
    _pj = {};
    _pj_snippets(_pj);
    trial_start = true;
    trial_number = 1;
    steps_count = 0;
    coins_count = 0;
    last_coins_count = coins_count;
    last_steps_count = steps_count;
    RT_block = [];
    block_timeout_count = 0;
    switch_occurred = false;
    block_type = tc_block_type;
    // instructions_type picks which Pigeon_<type>_InstructionsConditions.xlsx to show via
    // instructions_loop below; it's the block_type prefix before the first "_", so
    // "fixed_low"/"fixed_high" -> "fixed", "change_low"/"change_high" -> "change"
    // (see PigeonTaskConditions.xlsx / Resources/Pigeon_*_InstructionsConditions.xlsx).
    instructions_type = block_type.split("_")[0];
    step_mean = tc_step_mean;
    step_std = tc_step_std;
    // Testing only: a test_steps_max URL parameter (e.g. ?test_steps_max=100) shortens every
    // block. It is saved with expInfo in every data row, so test sessions are identifiable.
    steps_max = ('test_steps_max' in expInfo) ? parseInt(expInfo['test_steps_max']) : tc_steps_max;
    steps_taken_to_start_trial = tc_steps_taken_to_start_trial;
    steps_lost_per_error = tc_steps_lost_per_error;
    coins_max = tc_coins_max;
    coins_paid_to_start_trial = tc_coins_paid_to_start_trial;
    coins_gained_pre = tc_coins_gained_per_correct;
    coins_lost_pre = tc_coins_lost_per_error;
    coins_gained_post = tc_coins_gained_post;
    coins_lost_post = tc_coins_lost_post;
    coins_gained_per_correct = coins_gained_pre;
    coins_lost_per_error = coins_lost_pre;
    changepoint = tc_changepoint;
    // Icon for the reward in force: tree = high, cactus = low (pre-switch icon from the
    // conditions file; post-switch icon is the other one).
    pre_env_img = ("Resources/" + tc_img_file);
    post_env_img = (pre_env_img === high_env_img) ? low_env_img : high_env_img;
    env_img = pre_env_img;
    if ((changepoint === false)) {
        env_text = "";
    }
    instructions_conditions_file = (("Resources/Pigeon_" + instructions_type) + "_InstructionsConditions.xlsx");
    online_trials_count = 10000;
    block_number += 1;
    test_block_number += 1;
    message_string = ((("Testing Block " + test_block_number.toString()) + " of ") + experiment_loop.trialList.length.toString());
    pigeon_flip = 0.1;
    pigeon_true_x = 0;
    pigeon_shown_x = pigeon_true_x;
    steps_label = "Steps remaining";
    steps_text = (steps_max - steps_count).toString();
    update_status(true, true, true, changepoint);
    
    // keep track of which components have finished
    start_taskComponents = [];
    
    for (const thisComponent of start_taskComponents)
      if ('status' in thisComponent)
        thisComponent.status = PsychoJS.Status.NOT_STARTED;
    return Scheduler.Event.NEXT;
  }
}


function start_taskRoutineEachFrame() {
  return async function () {
    //--- Loop for each frame of Routine 'start_task' ---
    // get current time
    t = start_taskClock.getTime();
    frameN = frameN + 1;// number of completed frames (so 0 is the first frame)
    // update/draw components on each frame
    // check for quit (typically the Esc key)
    if (psychoJS.experiment.experimentEnded || psychoJS.eventManager.getKeys({keyList:['escape']}).length > 0) {
      return quitPsychoJS('The [Escape] key was pressed. Goodbye!', false);
    }
    
    // check if the Routine should terminate
    if (!continueRoutine) {  // a component has requested a forced-end of Routine
      return Scheduler.Event.NEXT;
    }
    
    continueRoutine = false;  // reverts to True if at least one component still running
    for (const thisComponent of start_taskComponents)
      if ('status' in thisComponent && thisComponent.status !== PsychoJS.Status.FINISHED) {
        continueRoutine = true;
        break;
      }
    
    // refresh the screen if continuing
    if (continueRoutine) {
      return Scheduler.Event.FLIP_REPEAT;
    } else {
      return Scheduler.Event.NEXT;
    }
  };
}


function start_taskRoutineEnd(snapshot) {
  return async function () {
    //--- Ending Routine 'start_task' ---
    for (const thisComponent of start_taskComponents) {
      if (typeof thisComponent.setAutoDraw === 'function') {
        thisComponent.setAutoDraw(false);
      }
    }
    // the Routine "start_task" was not non-slip safe, so reset the non-slip timer
    routineTimer.reset();
    
    // Routines running outside a loop should always advance the datafile row
    if (currentLoop === psychoJS.experiment) {
      psychoJS.experiment.nextEntry(snapshot);
    }
    return Scheduler.Event.NEXT;
  }
}


// ROUTINE PAIR "setup_instructions_message" + "show_message" (instructions_loop, run once
// per row of the block-type-specific Resources/Pigeon_<fixed|change>_InstructionsConditions.xlsx
// selected by start_task via instructions_conditions_file): shows the instructions specific
// to the block about to run, immediately before trial_loop starts.
var setup_instructions_messageComponents;
function setup_instructions_messageRoutineBegin(snapshot) {
  return async function () {
    TrialHandler.fromSnapshot(snapshot); // ensure that .thisN vals are up to date
    
    //--- Prepare to start Routine 'setup_instructions_message' ---
    t = 0;
    setup_instructions_messageClock.reset(); // clock
    frameN = -1;
    continueRoutine = true; // until we're told otherwise
    // update component parameters for each repeat
    // Run 'Begin Routine' code from code
    message_string = ic_message_string;
    
    // keep track of which components have finished
    setup_instructions_messageComponents = [];
    
    for (const thisComponent of setup_instructions_messageComponents)
      if ('status' in thisComponent)
        thisComponent.status = PsychoJS.Status.NOT_STARTED;
    return Scheduler.Event.NEXT;
  }
}


function setup_instructions_messageRoutineEachFrame() {
  return async function () {
    //--- Loop for each frame of Routine 'setup_instructions_message' ---
    // get current time
    t = setup_instructions_messageClock.getTime();
    frameN = frameN + 1;// number of completed frames (so 0 is the first frame)
    // update/draw components on each frame
    // check for quit (typically the Esc key)
    if (psychoJS.experiment.experimentEnded || psychoJS.eventManager.getKeys({keyList:['escape']}).length > 0) {
      return quitPsychoJS('The [Escape] key was pressed. Goodbye!', false);
    }
    
    // check if the Routine should terminate
    if (!continueRoutine) {  // a component has requested a forced-end of Routine
      return Scheduler.Event.NEXT;
    }
    
    continueRoutine = false;  // reverts to True if at least one component still running
    for (const thisComponent of setup_instructions_messageComponents)
      if ('status' in thisComponent && thisComponent.status !== PsychoJS.Status.FINISHED) {
        continueRoutine = true;
        break;
      }
    
    // refresh the screen if continuing
    if (continueRoutine) {
      return Scheduler.Event.FLIP_REPEAT;
    } else {
      return Scheduler.Event.NEXT;
    }
  };
}


function setup_instructions_messageRoutineEnd(snapshot) {
  return async function () {
    //--- Ending Routine 'setup_instructions_message' ---
    for (const thisComponent of setup_instructions_messageComponents) {
      if (typeof thisComponent.setAutoDraw === 'function') {
        thisComponent.setAutoDraw(false);
      }
    }
    // the Routine "setup_instructions_message" was not non-slip safe, so reset the non-slip timer
    routineTimer.reset();
    
    // Routines running outside a loop should always advance the datafile row
    if (currentLoop === psychoJS.experiment) {
      psychoJS.experiment.nextEntry(snapshot);
    }
    return Scheduler.Event.NEXT;
  }
}


// ROUTINE "task_run": the core per-step engine of the real task, called once per
// move_loop iteration (i.e. once per ~UPDATE_INTERVAL-second animation frame of Petey's
// walk). trial_start (true only for the first call of each trial, set by the preceding
// show_message's End Routine) selects between two modes on each call:
//   - trial_start === true: initialize a new trial -- pick this trial's SNR (change_*
//     blocks start at their block's own SNR), reset Petey to
//     center, draw a random correct_ans ("left"/"right") and the signed step_mean_val/
//     step_std_val consistent with it, and log the trial's design (step_mean_val,
//     step_std_val, block_number, trial_number, correct_ans, switch_time) to the data file.
//     No movement happens on this call; the participant sees Petey at center this frame.
//   - trial_start === false: advance the walk by one step (move_pigeon), apply the
//     changepoint SNR switch if this trial has just reached switch_time, and update the
//     on-screen countdown/status bars. The participant's Left/Right response (checked in
//     EachFrame below) can end the trial on any of these calls.
// Either way, if the block's cumulative steps_count has now reached steps_max the block
// itself ends (move_loop.finished = trial_loop.finished = true); task_runRoutineEnd still
// gives a same-frame Left/Right response priority over that block-end.
var _otr_kbd_response_allKeys;
var switch_time;
var steps_in_trial;
var correct_ans;
var task_runComponents;
function task_runRoutineBegin(snapshot) {
  return async function () {
    TrialHandler.fromSnapshot(snapshot); // ensure that .thisN vals are up to date
    
    //--- Prepare to start Routine 'task_run' ---
    t = 0;
    task_runClock.reset(); // clock
    frameN = -1;
    continueRoutine = true; // until we're told otherwise
    // update component parameters for each repeat
    otr_kbd_response.keys = undefined;
    otr_kbd_response.rt = undefined;
    _otr_kbd_response_allKeys = [];
    // Run 'Begin Routine' code from otr_code_update
    var _pj;
    function _pj_snippets(container) {
        function in_es6(left, right) {
            if (((right instanceof Array) || ((typeof right) === "string"))) {
                return (right.indexOf(left) > (- 1));
            } else {
                if (((right instanceof Map) || (right instanceof Set) || (right instanceof WeakMap) || (right instanceof WeakSet))) {
                    return right.has(left);
                } else {
                    return (left in right);
                }
            }
        }
        container["in_es6"] = in_es6;
        return container;
    }
    _pj = {};
    _pj_snippets(_pj);
    if ((trial_start === true)) {
        // --- New-trial setup ---
        // switch_time is only meaningful for change blocks (changepoint is false for fixed_*
        // blocks, so the reward-switch code later in this routine never consults it there).
        switch_time = fixed_switch_time;
        otr_kbd_response.clearEvents();
        message_string = NO_CHOICE_STRING;
        instruction_string = CHOICE_STRING;
        pigeon_flip = 0.1;
        pigeon_true_x = ORIGIN_X;
        pigeon_shown_x = pigeon_true_x;
        pigeon_steps = [pigeon_shown_x];
        // Every trial starts at the block's pre-switch reward; difficulty never changes.
        env_img = pre_env_img;
        coins_gained_per_correct = coins_gained_pre;
        coins_lost_per_error = coins_lost_pre;
        if (changepoint) {
            env_bar_height = ENV_BAR_HEIGHT;
        }
        switch_occurred = false;
        coins_count += coins_paid_to_start_trial;
        steps_count += steps_taken_to_start_trial;
        steps_in_trial = 0;
        // Draw this trial's ground-truth direction uniformly and sign step_mean_val to
        // match: correct_ans records which side Petey is actually biased toward, and the
        // participant's response is scored against it in task_runRoutineEnd.
        if ((util.randint(0, 2) === 1)) {
            correct_ans = "right";
            step_mean_val = Math.abs(step_mean);
        } else {
            correct_ans = "left";
            step_mean_val = ((- 1) * Math.abs(step_mean));
        }
        step_std_val = step_std;
        psychoJS.experiment.addData("step_mean_val", step_mean_val);
        psychoJS.experiment.addData("step_std_val", step_std_val);
        psychoJS.experiment.addData("block_number", block_number);
        psychoJS.experiment.addData("trial_number", trial_number);
        psychoJS.experiment.addData("correct", correct_ans);
        // Record the changepoint step directly, per trial, so downstream
        // analysis reads it rather than re-deriving it from RTs (which would
        // need to independently replicate the exact trimming/rounding used
        // to compute fixed_switch_time).
        if (changepoint) {
            psychoJS.experiment.addData("switch_time", switch_time);
        }
        psychoJS.experiment.addData("block_order", block_order);
        psychoJS.experiment.addData("coins_gained_pre", coins_gained_pre);
        psychoJS.experiment.addData("coins_lost_pre", coins_lost_pre);
        psychoJS.experiment.addData("coins_gained_post", coins_gained_post);
        psychoJS.experiment.addData("coins_lost_post", coins_lost_post);
        trial_start = false;
        update_status(true, false, false, false);
        steps_text = (steps_max - steps_count).toString();
        coins_text = coins_count.toString();
        if (changepoint) {
            env_text = (switch_time - steps_in_trial).toString();
        }
        update_status(false, false, false, changepoint);
    } else {
        // --- One animation step of an in-progress trial ---
        steps_count += 1;
        steps_in_trial += 1;
        if (((changepoint === true) && (steps_in_trial < switch_time))) {
            env_text = (switch_time - steps_in_trial).toString();
        } else {
            env_text = "";
        }
        steps_text = (steps_max - steps_count).toString();
        // Reward switch: from this step on, a response is scored with the post-switch coin
        // values (the walk itself is unchanged).
        if (((changepoint === true) && (switch_occurred === false) && (steps_in_trial === switch_time))) {
            env_bar_height = 0;
            env_img = post_env_img;
            coins_gained_per_correct = coins_gained_post;
            coins_lost_per_error = coins_lost_post;
            switch_occurred = true;
            update_status(true, false, false, false);
        }
        move_pigeon(step_mean_val, step_std_val);
        pigeon_steps.push(pigeon_shown_x);
        update_status(true, false, true, changepoint);
    }
    // Block-level budget check: steps_count is cumulative across every trial in the block
    // (bumped by move_pigeon steps, steps_taken_to_start_trial, and steps_lost_per_error),
    // so this fires once, on whichever call first pushes it to/past steps_max. Ending the
    // block here (move_loop.finished/trial_loop.finished = true) takes effect in
    // task_runRoutineEnd, which still gives priority to a Left/Right response captured by
    // this same call's EachFrame over the block having ended (see the comment there).
    if ((steps_count >= steps_max)) {
        move_loop.finished = true;
        trial_loop.finished = true;
        // After each fixed block, add its (warm-up-trimmed) RTs and timeouts to the pooled
        // totals; after the second, set the change blocks' switch_time and run the RT screen
        // on the pooled fixed-block data.
        if (changepoint === false) {
            fixed_rts_pooled = fixed_rts_pooled.concat(trim_warmup_trials(RT_block));
            fixed_timeouts_pooled += block_timeout_count;
            fixed_blocks_done += 1;
            if (fixed_blocks_done === 2) {
                fixed_switch_time = calculate_median(fixed_rts_pooled.slice());
                let total_attempted = fixed_rts_pooled.length + fixed_timeouts_pooled;
                let timeout_fraction = total_attempted > 0 ? (fixed_timeouts_pooled / total_attempted) : 0;
                let exclusion_reason = check_rt_extremity(fixed_rts_pooled, timeout_fraction);
                psychoJS.experiment.addData("fixed_switch_time", fixed_switch_time);
                if (exclusion_reason !== null) {
                    should_exclude_participant = true;
                    exclusion_message = (exclusion_reason === "too_fast") ? RT_TOO_FAST_MESSAGE : RT_TOO_SLOW_MESSAGE;
                    experiment_loop.finished = true;
                }
            }
        }
    }

    otr_polygon_abscissa.setPos([ORIGIN_X, ABSCISSA_Y]);
    otr_polygon_abscissa.setSize([(EDGE_DISTANCE * 2), LINE_HEIGHT]);
    otr_polygon_ordinate.setPos([ORIGIN_X, ORDINATE_Y]);
    otr_polygon_ordinate.setSize([ORDINATE_WIDTH, ORDINATE_HEIGHT]);
    otr_polygon_petey_midpoint.setPos([pigeon_shown_x, ORDINATE_Y]);
    otr_polygon_petey_midpoint.setSize([(ORDINATE_WIDTH * 0.9), ORDINATE_HEIGHT]);
    otr_image_pigeon.setPos([pigeon_shown_x, ORIGIN_Y]);
    otr_image_pigeon.setSize([pigeon_flip, 0.1]);
    otr_image_right_seeds.setSize([(SEEDS_SCALE * SEEDS_WIDTH), (SEEDS_SCALE * SEEDS_HEIGHT)]);
    otr_image_left_seeds.setSize([(SEEDS_SCALE * SEEDS_WIDTH), (SEEDS_SCALE * SEEDS_HEIGHT)]);
    otr_image_env.setImage(env_img);
    otr_polygon_changepoint_bar.setPos([env_bar_center, (ENV_Y - 0.06)]);
    otr_polygon_changepoint_bar.setSize([env_bar_width, env_bar_height]);
    otr_polygon_coins_bar.setPos([COINS_BAR_X, coins_bar_center]);
    otr_polygon_coins_bar.setSize([STATUS_BAR_WIDTH, coins_bar_height]);
    otr_polygon_steps_bar.setPos([STEPS_BAR_X, steps_bar_center]);
    otr_polygon_steps_bar.setSize([STATUS_BAR_WIDTH, steps_bar_height]);
    otr_polygon_status_bar_apex.setPos([ORIGIN_X, STATUS_BAR_APEX_Y]);
    otr_polygon_status_bar_apex.setSize([STATUS_BAR_BRACKET_WIDTH, LINE_HEIGHT]);
    otr_polygon_status_bar_base.setPos([ORIGIN_X, STATUS_BAR_BASE_Y]);
    otr_polygon_status_bar_base.setSize([STATUS_BAR_BRACKET_WIDTH, LINE_HEIGHT]);
    otr_text_env.setText(env_text);
    otr_text_coins.setText(coins_text);
    otr_text_coins_properties.setText(coins_string);
    otr_text_steps.setText(steps_text);
    otr_text_steps_label.setText(steps_label);
    otr_text_steps_properties.setText(steps_string);
    otr_text_instruction.setText(instruction_string);
    // keep track of which components have finished
    task_runComponents = [];
    task_runComponents.push(otr_kbd_response);
    task_runComponents.push(otr_polygon_abscissa);
    task_runComponents.push(otr_polygon_ordinate);
    task_runComponents.push(otr_polygon_petey_midpoint);
    task_runComponents.push(otr_image_pigeon);
    task_runComponents.push(otr_image_right_seeds);
    task_runComponents.push(otr_image_left_seeds);
    task_runComponents.push(otr_image_env);
    task_runComponents.push(otr_polygon_changepoint_bar);
    task_runComponents.push(otr_polygon_coins_bar);
    task_runComponents.push(otr_polygon_steps_bar);
    task_runComponents.push(otr_polygon_status_bar_apex);
    task_runComponents.push(otr_polygon_status_bar_base);
    task_runComponents.push(otr_text_env);
    task_runComponents.push(otr_text_coins);
    task_runComponents.push(otr_text_coins_label);
    task_runComponents.push(otr_text_coins_properties);
    task_runComponents.push(otr_text_steps);
    task_runComponents.push(otr_text_steps_label);
    task_runComponents.push(otr_text_steps_properties);
    task_runComponents.push(otr_text_instruction);
    
    for (const thisComponent of task_runComponents)
      if ('status' in thisComponent)
        thisComponent.status = PsychoJS.Status.NOT_STARTED;
    return Scheduler.Event.NEXT;
  }
}


function task_runRoutineEachFrame() {
  return async function () {
    //--- Loop for each frame of Routine 'task_run' ---
    // get current time
    t = task_runClock.getTime();
    frameN = frameN + 1;// number of completed frames (so 0 is the first frame)
    // update/draw components on each frame
    
    // *otr_kbd_response* updates
    if (t >= 0.0 && otr_kbd_response.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      otr_kbd_response.tStart = t;  // (not accounting for frame time here)
      otr_kbd_response.frameNStart = frameN;  // exact frame index
      
      // keyboard checking is just starting
      psychoJS.window.callOnFlip(function() { otr_kbd_response.clock.reset(); });  // t=0 on next screen flip
      psychoJS.window.callOnFlip(function() { otr_kbd_response.start(); }); // start on screen flip
    }

    frameRemains = 0.0 + UPDATE_INTERVAL - psychoJS.window.monitorFramePeriod * 0.75;  // most of one frame period left
    if (otr_kbd_response.status === PsychoJS.Status.STARTED && t >= frameRemains) {
      otr_kbd_response.status = PsychoJS.Status.FINISHED;
  }

    if (otr_kbd_response.status === PsychoJS.Status.STARTED) {
      let theseKeys = otr_kbd_response.getKeys({keyList: ['left', 'right'], waitRelease: false});
      _otr_kbd_response_allKeys = _otr_kbd_response_allKeys.concat(theseKeys);
      if (_otr_kbd_response_allKeys.length > 0) {
        otr_kbd_response.keys = _otr_kbd_response_allKeys[_otr_kbd_response_allKeys.length - 1].name;  // just the last key pressed
        otr_kbd_response.rt = _otr_kbd_response_allKeys[_otr_kbd_response_allKeys.length - 1].rt;
        // a response ends the routine
        continueRoutine = false;
      }
    }
    
    
    // *otr_polygon_abscissa* updates
    if (t >= 0 && otr_polygon_abscissa.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      otr_polygon_abscissa.tStart = t;  // (not accounting for frame time here)
      otr_polygon_abscissa.frameNStart = frameN;  // exact frame index
      
      otr_polygon_abscissa.setAutoDraw(true);
    }

    frameRemains = 0 + UPDATE_INTERVAL - psychoJS.window.monitorFramePeriod * 0.75;  // most of one frame period left
    if (otr_polygon_abscissa.status === PsychoJS.Status.STARTED && t >= frameRemains) {
      otr_polygon_abscissa.setAutoDraw(false);
    }
    
    // *otr_polygon_ordinate* updates
    if (t >= 0 && otr_polygon_ordinate.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      otr_polygon_ordinate.tStart = t;  // (not accounting for frame time here)
      otr_polygon_ordinate.frameNStart = frameN;  // exact frame index
      
      otr_polygon_ordinate.setAutoDraw(true);
    }

    frameRemains = 0 + UPDATE_INTERVAL - psychoJS.window.monitorFramePeriod * 0.75;  // most of one frame period left
    if (otr_polygon_ordinate.status === PsychoJS.Status.STARTED && t >= frameRemains) {
      otr_polygon_ordinate.setAutoDraw(false);
    }
    
    // *otr_polygon_petey_midpoint* updates
    if (t >= 0.0 && otr_polygon_petey_midpoint.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      otr_polygon_petey_midpoint.tStart = t;  // (not accounting for frame time here)
      otr_polygon_petey_midpoint.frameNStart = frameN;  // exact frame index
      
      otr_polygon_petey_midpoint.setAutoDraw(true);
    }

    frameRemains = 0.0 + UPDATE_INTERVAL - psychoJS.window.monitorFramePeriod * 0.75;  // most of one frame period left
    if (otr_polygon_petey_midpoint.status === PsychoJS.Status.STARTED && t >= frameRemains) {
      otr_polygon_petey_midpoint.setAutoDraw(false);
    }
    
    // *otr_image_pigeon* updates
    if (t >= 0.0 && otr_image_pigeon.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      otr_image_pigeon.tStart = t;  // (not accounting for frame time here)
      otr_image_pigeon.frameNStart = frameN;  // exact frame index
      
      otr_image_pigeon.setAutoDraw(true);
    }

    frameRemains = 0.0 + UPDATE_INTERVAL - psychoJS.window.monitorFramePeriod * 0.75;  // most of one frame period left
    if (otr_image_pigeon.status === PsychoJS.Status.STARTED && t >= frameRemains) {
      otr_image_pigeon.setAutoDraw(false);
    }
    
    // *otr_image_right_seeds* updates
    if (t >= 0.0 && otr_image_right_seeds.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      otr_image_right_seeds.tStart = t;  // (not accounting for frame time here)
      otr_image_right_seeds.frameNStart = frameN;  // exact frame index
      
      otr_image_right_seeds.setAutoDraw(true);
    }

    frameRemains = 0.0 + UPDATE_INTERVAL - psychoJS.window.monitorFramePeriod * 0.75;  // most of one frame period left
    if (otr_image_right_seeds.status === PsychoJS.Status.STARTED && t >= frameRemains) {
      otr_image_right_seeds.setAutoDraw(false);
    }
    
    // *otr_image_left_seeds* updates
    if (t >= 0.0 && otr_image_left_seeds.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      otr_image_left_seeds.tStart = t;  // (not accounting for frame time here)
      otr_image_left_seeds.frameNStart = frameN;  // exact frame index
      
      otr_image_left_seeds.setAutoDraw(true);
    }

    frameRemains = 0.0 + UPDATE_INTERVAL - psychoJS.window.monitorFramePeriod * 0.75;  // most of one frame period left
    if (otr_image_left_seeds.status === PsychoJS.Status.STARTED && t >= frameRemains) {
      otr_image_left_seeds.setAutoDraw(false);
    }
    
    // *otr_image_env* updates
    if (t >= 0 && otr_image_env.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      otr_image_env.tStart = t;  // (not accounting for frame time here)
      otr_image_env.frameNStart = frameN;  // exact frame index
      
      otr_image_env.setAutoDraw(true);
    }

    frameRemains = 0 + UPDATE_INTERVAL - psychoJS.window.monitorFramePeriod * 0.75;  // most of one frame period left
    if (otr_image_env.status === PsychoJS.Status.STARTED && t >= frameRemains) {
      otr_image_env.setAutoDraw(false);
    }
    
    // *otr_polygon_changepoint_bar* updates
    if (t >= 0 && otr_polygon_changepoint_bar.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      otr_polygon_changepoint_bar.tStart = t;  // (not accounting for frame time here)
      otr_polygon_changepoint_bar.frameNStart = frameN;  // exact frame index
      
      otr_polygon_changepoint_bar.setAutoDraw(true);
    }

    frameRemains = 0 + UPDATE_INTERVAL - psychoJS.window.monitorFramePeriod * 0.75;  // most of one frame period left
    if (otr_polygon_changepoint_bar.status === PsychoJS.Status.STARTED && t >= frameRemains) {
      otr_polygon_changepoint_bar.setAutoDraw(false);
    }
    
    // *otr_polygon_coins_bar* updates
    if (t >= 0.0 && otr_polygon_coins_bar.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      otr_polygon_coins_bar.tStart = t;  // (not accounting for frame time here)
      otr_polygon_coins_bar.frameNStart = frameN;  // exact frame index
      
      otr_polygon_coins_bar.setAutoDraw(true);
    }

    frameRemains = 0.0 + UPDATE_INTERVAL - psychoJS.window.monitorFramePeriod * 0.75;  // most of one frame period left
    if (otr_polygon_coins_bar.status === PsychoJS.Status.STARTED && t >= frameRemains) {
      otr_polygon_coins_bar.setAutoDraw(false);
    }
    
    // *otr_polygon_steps_bar* updates
    if (t >= 0.0 && otr_polygon_steps_bar.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      otr_polygon_steps_bar.tStart = t;  // (not accounting for frame time here)
      otr_polygon_steps_bar.frameNStart = frameN;  // exact frame index
      
      otr_polygon_steps_bar.setAutoDraw(true);
    }

    frameRemains = 0.0 + UPDATE_INTERVAL - psychoJS.window.monitorFramePeriod * 0.75;  // most of one frame period left
    if (otr_polygon_steps_bar.status === PsychoJS.Status.STARTED && t >= frameRemains) {
      otr_polygon_steps_bar.setAutoDraw(false);
    }
    
    // *otr_polygon_status_bar_apex* updates
    if (t >= 0.0 && otr_polygon_status_bar_apex.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      otr_polygon_status_bar_apex.tStart = t;  // (not accounting for frame time here)
      otr_polygon_status_bar_apex.frameNStart = frameN;  // exact frame index
      
      otr_polygon_status_bar_apex.setAutoDraw(true);
    }

    frameRemains = 0.0 + UPDATE_INTERVAL - psychoJS.window.monitorFramePeriod * 0.75;  // most of one frame period left
    if (otr_polygon_status_bar_apex.status === PsychoJS.Status.STARTED && t >= frameRemains) {
      otr_polygon_status_bar_apex.setAutoDraw(false);
    }
    
    // *otr_polygon_status_bar_base* updates
    if (t >= 0.0 && otr_polygon_status_bar_base.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      otr_polygon_status_bar_base.tStart = t;  // (not accounting for frame time here)
      otr_polygon_status_bar_base.frameNStart = frameN;  // exact frame index
      
      otr_polygon_status_bar_base.setAutoDraw(true);
    }

    frameRemains = 0.0 + UPDATE_INTERVAL - psychoJS.window.monitorFramePeriod * 0.75;  // most of one frame period left
    if (otr_polygon_status_bar_base.status === PsychoJS.Status.STARTED && t >= frameRemains) {
      otr_polygon_status_bar_base.setAutoDraw(false);
    }
    
    // *otr_text_env* updates
    if (t >= 0.0 && otr_text_env.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      otr_text_env.tStart = t;  // (not accounting for frame time here)
      otr_text_env.frameNStart = frameN;  // exact frame index
      
      otr_text_env.setAutoDraw(true);
    }

    frameRemains = 0.0 + UPDATE_INTERVAL - psychoJS.window.monitorFramePeriod * 0.75;  // most of one frame period left
    if (otr_text_env.status === PsychoJS.Status.STARTED && t >= frameRemains) {
      otr_text_env.setAutoDraw(false);
    }
    
    // *otr_text_coins* updates
    if (t >= 0.0 && otr_text_coins.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      otr_text_coins.tStart = t;  // (not accounting for frame time here)
      otr_text_coins.frameNStart = frameN;  // exact frame index
      
      otr_text_coins.setAutoDraw(true);
    }

    frameRemains = 0.0 + UPDATE_INTERVAL - psychoJS.window.monitorFramePeriod * 0.75;  // most of one frame period left
    if (otr_text_coins.status === PsychoJS.Status.STARTED && t >= frameRemains) {
      otr_text_coins.setAutoDraw(false);
    }
    
    // *otr_text_coins_label* updates
    if (t >= 0.0 && otr_text_coins_label.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      otr_text_coins_label.tStart = t;  // (not accounting for frame time here)
      otr_text_coins_label.frameNStart = frameN;  // exact frame index
      
      otr_text_coins_label.setAutoDraw(true);
    }

    frameRemains = 0.0 + UPDATE_INTERVAL - psychoJS.window.monitorFramePeriod * 0.75;  // most of one frame period left
    if (otr_text_coins_label.status === PsychoJS.Status.STARTED && t >= frameRemains) {
      otr_text_coins_label.setAutoDraw(false);
    }
    
    // *otr_text_coins_properties* updates
    if (t >= 0.0 && otr_text_coins_properties.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      otr_text_coins_properties.tStart = t;  // (not accounting for frame time here)
      otr_text_coins_properties.frameNStart = frameN;  // exact frame index
      
      otr_text_coins_properties.setAutoDraw(true);
    }

    frameRemains = 0.0 + UPDATE_INTERVAL - psychoJS.window.monitorFramePeriod * 0.75;  // most of one frame period left
    if (otr_text_coins_properties.status === PsychoJS.Status.STARTED && t >= frameRemains) {
      otr_text_coins_properties.setAutoDraw(false);
    }
    
    // *otr_text_steps* updates
    if (t >= 0.0 && otr_text_steps.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      otr_text_steps.tStart = t;  // (not accounting for frame time here)
      otr_text_steps.frameNStart = frameN;  // exact frame index
      
      otr_text_steps.setAutoDraw(true);
    }

    frameRemains = 0.0 + UPDATE_INTERVAL - psychoJS.window.monitorFramePeriod * 0.75;  // most of one frame period left
    if (otr_text_steps.status === PsychoJS.Status.STARTED && t >= frameRemains) {
      otr_text_steps.setAutoDraw(false);
    }
    
    // *otr_text_steps_label* updates
    if (t >= 0.0 && otr_text_steps_label.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      otr_text_steps_label.tStart = t;  // (not accounting for frame time here)
      otr_text_steps_label.frameNStart = frameN;  // exact frame index
      
      otr_text_steps_label.setAutoDraw(true);
    }

    frameRemains = 0.0 + UPDATE_INTERVAL - psychoJS.window.monitorFramePeriod * 0.75;  // most of one frame period left
    if (otr_text_steps_label.status === PsychoJS.Status.STARTED && t >= frameRemains) {
      otr_text_steps_label.setAutoDraw(false);
    }
    
    // *otr_text_steps_properties* updates
    if (t >= 0.0 && otr_text_steps_properties.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      otr_text_steps_properties.tStart = t;  // (not accounting for frame time here)
      otr_text_steps_properties.frameNStart = frameN;  // exact frame index
      
      otr_text_steps_properties.setAutoDraw(true);
    }

    frameRemains = 0.0 + UPDATE_INTERVAL - psychoJS.window.monitorFramePeriod * 0.75;  // most of one frame period left
    if (otr_text_steps_properties.status === PsychoJS.Status.STARTED && t >= frameRemains) {
      otr_text_steps_properties.setAutoDraw(false);
    }
    
    // *otr_text_instruction* updates
    if (t >= 0.0 && otr_text_instruction.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      otr_text_instruction.tStart = t;  // (not accounting for frame time here)
      otr_text_instruction.frameNStart = frameN;  // exact frame index
      
      otr_text_instruction.setAutoDraw(true);
    }

    frameRemains = 0.0 + UPDATE_INTERVAL - psychoJS.window.monitorFramePeriod * 0.75;  // most of one frame period left
    if (otr_text_instruction.status === PsychoJS.Status.STARTED && t >= frameRemains) {
      otr_text_instruction.setAutoDraw(false);
    }
    // check for quit (typically the Esc key)
    if (psychoJS.experiment.experimentEnded || psychoJS.eventManager.getKeys({keyList:['escape']}).length > 0) {
      return quitPsychoJS('The [Escape] key was pressed. Goodbye!', false);
    }
    
    // check if the Routine should terminate
    if (!continueRoutine) {  // a component has requested a forced-end of Routine
      return Scheduler.Event.NEXT;
    }
    
    continueRoutine = false;  // reverts to True if at least one component still running
    for (const thisComponent of task_runComponents)
      if ('status' in thisComponent && thisComponent.status !== PsychoJS.Status.FINISHED) {
        continueRoutine = true;
        break;
      }
    
    // refresh the screen if continuing
    if (continueRoutine) {
      return Scheduler.Event.FLIP_REPEAT;
    } else {
      return Scheduler.Event.NEXT;
    }
  };
}


function task_runRoutineEnd(snapshot) {
  return async function () {
    //--- Ending Routine 'task_run' ---
    for (const thisComponent of task_runComponents) {
      if (typeof thisComponent.setAutoDraw === 'function') {
        thisComponent.setAutoDraw(false);
      }
    }
    otr_kbd_response.stop();
    // Run 'End Routine' code from otr_code_update
    var _pj;
    function _pj_snippets(container) {
        function in_es6(left, right) {
            if (((right instanceof Array) || ((typeof right) === "string"))) {
                return (right.indexOf(left) > (- 1));
            } else {
                if (((right instanceof Map) || (right instanceof Set) || (right instanceof WeakMap) || (right instanceof WeakSet))) {
                    return right.has(left);
                } else {
                    return (left in right);
                }
            }
        }
        container["in_es6"] = in_es6;
        return container;
    }
    _pj = {};
    _pj_snippets(_pj);
    // FIX: a genuine response takes priority over the block-budget end. If the participant
    // pressed Left/Right on this exact frame, score and log it as a real trial even if the
    // block's step budget was *also* exhausted on this same step (trial_loop.finished may
    // already be true -- see the block-budget check in Begin Routine above). Previously this
    // branched on trial_loop.finished first, which silently discarded that response (always
    // recorded as choice "none") whenever it happened to coincide with the block ending.
    if (otr_kbd_response.keys) {
        // otr_kbd_response.keys is only "left" or "right" (see the keyList in EachFrame
        // above); in_es6(correct_ans, otr_kbd_response.keys) is a substring/membership
        // check that reduces to correct_ans === otr_kbd_response.keys for this keyList.
        if (_pj.in_es6(correct_ans, otr_kbd_response.keys)) {
            coins_count += coins_gained_per_correct;
            set_trial_end_string(CORRECT_STRING);
            update_status(false, true, false, _pj.in_es6("change", block_type));
        } else {
            coins_count -= coins_lost_per_error;
            steps_count += steps_lost_per_error;
            set_trial_end_string(ERROR_STRING);
        }
        psychoJS.experiment.addData("pigeon_steps", pigeon_steps);
        psychoJS.experiment.addData("coins_count", coins_count);
        psychoJS.experiment.addData("steps_count", steps_count);
        psychoJS.experiment.addData("choice", otr_kbd_response.keys);
        update_status(false, true, true, changepoint);
        otr_kbd_response.clearEvents();
        if (changepoint === false) {
            RT_block.push(pigeon_steps.length);
        }
        trial_number += 1;
        move_loop.finished = true;
    } else if (trial_loop.finished === true) {
        // Block budget ran out on this step with no response captured this frame.
        steps_count = steps_max;
        psychoJS.experiment.addData("pigeon_steps", pigeon_steps);
        psychoJS.experiment.addData("coins_count", coins_count);
        psychoJS.experiment.addData("steps_count", steps_count);
        psychoJS.experiment.addData("choice", "none");
    } else {
        // No key this frame: time out the trial once move_loop's own repeat counter
        // (0-indexed) reaches STEPS_MAX_PER_TRIAL - 1, i.e. after STEPS_MAX_PER_TRIAL
        // task_run calls for this trial (the first of which was the trial_start === true
        // setup call that didn't move Petey, so this is STEPS_MAX_PER_TRIAL - 1 actual
        // movement steps). No response is recorded either way.
        if ((move_loop.thisRepN === (STEPS_MAX_PER_TRIAL - 1))) {
            move_loop.finished = true;
            set_trial_end_string(NO_CHOICE_STRING);
            trial_number += 1;
            psychoJS.experiment.addData("pigeon_steps", pigeon_steps);
            psychoJS.experiment.addData("coins_count", coins_count);
            psychoJS.experiment.addData("steps_count", steps_count);
            psychoJS.experiment.addData("choice", "none");
            // Tracked separately from RT_block (which only ever holds responded trials'
            // RTs) so check_rt_extremity can see the real per-trial timeout rate.
            if (changepoint === false) {
                block_timeout_count += 1;
            }
        }
    }
    // Block-end bookkeeping runs regardless of which branch above fired, and after any
    // response this frame has already been scored, so set_block_end_string's coins_count
    // check reflects this trial's outcome too.
    if (trial_loop.finished === true) {
        set_block_end_string();
        psychoJS.experiment.addData("bonus", bonus_count);
    }

    // the Routine "task_run" was not non-slip safe, so reset the non-slip timer
    routineTimer.reset();
    
    // Routines running outside a loop should always advance the datafile row
    if (currentLoop === psychoJS.experiment) {
      psychoJS.experiment.nextEntry(snapshot);
    }
    return Scheduler.Event.NEXT;
  }
}


// ROUTINE "final_message" -> "show_final_message": runs once, after experiment_loop ends
// (either normally, or early via experiment_loop.finished = true when the RT-extremity
// exclusion check in otr_code_update fires). Picks the closing message: the RT-extremity
// exclusion message if should_exclude_participant, otherwise a generic completion message.
var final_messageComponents;
function final_messageRoutineBegin(snapshot) {
  return async function () {
    TrialHandler.fromSnapshot(snapshot); // ensure that .thisN vals are up to date
    
    //--- Prepare to start Routine 'final_message' ---
    t = 0;
    final_messageClock.reset(); // clock
    frameN = -1;
    continueRoutine = true; // until we're told otherwise
    // update component parameters for each repeat
    // Run 'Begin Routine' code from fm_code_setup
    message_string = should_exclude_participant ? exclusion_message : "Finished, fantastic job!";
    
    // keep track of which components have finished
    final_messageComponents = [];
    
    for (const thisComponent of final_messageComponents)
      if ('status' in thisComponent)
        thisComponent.status = PsychoJS.Status.NOT_STARTED;
    return Scheduler.Event.NEXT;
  }
}


function final_messageRoutineEachFrame() {
  return async function () {
    //--- Loop for each frame of Routine 'final_message' ---
    // get current time
    t = final_messageClock.getTime();
    frameN = frameN + 1;// number of completed frames (so 0 is the first frame)
    // update/draw components on each frame
    // check for quit (typically the Esc key)
    if (psychoJS.experiment.experimentEnded || psychoJS.eventManager.getKeys({keyList:['escape']}).length > 0) {
      return quitPsychoJS('The [Escape] key was pressed. Goodbye!', false);
    }
    
    // check if the Routine should terminate
    if (!continueRoutine) {  // a component has requested a forced-end of Routine
      return Scheduler.Event.NEXT;
    }
    
    continueRoutine = false;  // reverts to True if at least one component still running
    for (const thisComponent of final_messageComponents)
      if ('status' in thisComponent && thisComponent.status !== PsychoJS.Status.FINISHED) {
        continueRoutine = true;
        break;
      }
    
    // refresh the screen if continuing
    if (continueRoutine) {
      return Scheduler.Event.FLIP_REPEAT;
    } else {
      return Scheduler.Event.NEXT;
    }
  };
}


function final_messageRoutineEnd(snapshot) {
  return async function () {
    //--- Ending Routine 'final_message' ---
    for (const thisComponent of final_messageComponents) {
      if (typeof thisComponent.setAutoDraw === 'function') {
        thisComponent.setAutoDraw(false);
      }
    }
    // the Routine "final_message" was not non-slip safe, so reset the non-slip timer
    routineTimer.reset();
    
    // Routines running outside a loop should always advance the datafile row
    if (currentLoop === psychoJS.experiment) {
      psychoJS.experiment.nextEntry(snapshot);
    }
    return Scheduler.Event.NEXT;
  }
}


// ROUTINE "show_final_message": the closing screen, waits (from t=0.5s) for a
// space/arrow keypress before quitting. Displays the message set by final_message plus a
// final snapshot of the coins/steps status bars from whatever state they were left in.
var _sfm_kbd_continue_allKeys;
var show_final_messageComponents;
function show_final_messageRoutineBegin(snapshot) {
  return async function () {
    TrialHandler.fromSnapshot(snapshot); // ensure that .thisN vals are up to date
    
    //--- Prepare to start Routine 'show_final_message' ---
    t = 0;
    show_final_messageClock.reset(); // clock
    frameN = -1;
    continueRoutine = true; // until we're told otherwise
    // update component parameters for each repeat
    sfm_kbd_continue.keys = undefined;
    sfm_kbd_continue.rt = undefined;
    _sfm_kbd_continue_allKeys = [];
    // Run 'Begin Routine' code from sfm_code_update
    // FIX: this used to clear sm_kbd_continue (show_message's keyboard, unused by this
    // routine) instead of sfm_kbd_continue (this routine's own keyboard, pushed into
    // show_final_messageComponents just below) -- a copy/paste leftover from sm_code_update.
    sfm_kbd_continue.clearEvents();

    sfm_text_message.setText(message_string);
    sfm_text_steps_properties.setText(steps_string);
    sfm_text_steps.setText((steps_max - steps_count));
    sfm_text_coins_properties.setText(coins_string);
    sfm_text_coins.setText(coins_count);
    sfm_polygon_status_bar_base.setPos([ORIGIN_X, STATUS_BAR_BASE_Y]);
    sfm_polygon_status_bar_base.setSize([STATUS_BAR_BRACKET_WIDTH, LINE_HEIGHT]);
    sfm_polygon_status_bar_apex.setPos([ORIGIN_X, STATUS_BAR_APEX_Y]);
    sfm_polygon_status_bar_apex.setSize([STATUS_BAR_BRACKET_WIDTH, LINE_HEIGHT]);
    sfm_polygon_steps_bar.setPos([STEPS_BAR_X, steps_bar_center]);
    sfm_polygon_steps_bar.setSize([STATUS_BAR_WIDTH, steps_bar_height]);
    sfm_polygon_coin_bar.setPos([COINS_BAR_X, coins_bar_center]);
    sfm_polygon_coin_bar.setSize([STATUS_BAR_WIDTH, coins_bar_height]);
    sfm_image_petey.setPos([pigeon_shown_x, ORIGIN_Y]);
    sfm_image_petey.setSize([pigeon_flip, 0.1]);
    sfm_polygon_petey_midpoint.setPos([pigeon_shown_x, ORDINATE_Y]);
    sfm_polygon_petey_midpoint.setSize([(ORDINATE_WIDTH * 0.9), ORDINATE_HEIGHT]);
    sfm_polygon_ordinate.setPos([ORIGIN_X, ORDINATE_Y]);
    sfm_polygon_ordinate.setSize([ORDINATE_WIDTH, ORDINATE_HEIGHT]);
    sfm_polygon_abscissa.setPos([ORIGIN_X, ABSCISSA_Y]);
    sfm_polygon_abscissa.setSize([ABSCISSA_WIDTH, LINE_HEIGHT]);
    sfm_polygon_box.setPos([box_x, box_y]);
    sfm_polygon_box.setSize([box_width, box_height]);
    sfm_text_instruction.setText(CONTINUE_STRING);
    // keep track of which components have finished
    show_final_messageComponents = [];
    show_final_messageComponents.push(sfm_kbd_continue);
    show_final_messageComponents.push(sfm_text_message);
    show_final_messageComponents.push(sfm_text_steps_properties);
    show_final_messageComponents.push(sfm_text_steps_label);
    show_final_messageComponents.push(sfm_text_steps);
    show_final_messageComponents.push(sfm_text_coins_properties);
    show_final_messageComponents.push(sfm_text_coins_label);
    show_final_messageComponents.push(sfm_text_coins);
    show_final_messageComponents.push(sfm_polygon_status_bar_base);
    show_final_messageComponents.push(sfm_polygon_status_bar_apex);
    show_final_messageComponents.push(sfm_polygon_steps_bar);
    show_final_messageComponents.push(sfm_polygon_coin_bar);
    show_final_messageComponents.push(sfm_image_petey);
    show_final_messageComponents.push(sfm_image_left_seeds);
    show_final_messageComponents.push(sfm_image_right_seeds);
    show_final_messageComponents.push(sfm_polygon_petey_midpoint);
    show_final_messageComponents.push(sfm_polygon_ordinate);
    show_final_messageComponents.push(sfm_polygon_abscissa);
    show_final_messageComponents.push(sfm_polygon_box);
    show_final_messageComponents.push(sfm_text_instruction);
    
    for (const thisComponent of show_final_messageComponents)
      if ('status' in thisComponent)
        thisComponent.status = PsychoJS.Status.NOT_STARTED;
    return Scheduler.Event.NEXT;
  }
}


function show_final_messageRoutineEachFrame() {
  return async function () {
    //--- Loop for each frame of Routine 'show_final_message' ---
    // get current time
    t = show_final_messageClock.getTime();
    frameN = frameN + 1;// number of completed frames (so 0 is the first frame)
    // update/draw components on each frame
    
    // *sfm_kbd_continue* updates
    if (t >= 0.5 && sfm_kbd_continue.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sfm_kbd_continue.tStart = t;  // (not accounting for frame time here)
      sfm_kbd_continue.frameNStart = frameN;  // exact frame index
      
      // keyboard checking is just starting
      psychoJS.window.callOnFlip(function() { sfm_kbd_continue.clock.reset(); });  // t=0 on next screen flip
      psychoJS.window.callOnFlip(function() { sfm_kbd_continue.start(); }); // start on screen flip
      psychoJS.window.callOnFlip(function() { sfm_kbd_continue.clearEvents(); });
    }

    if (sfm_kbd_continue.status === PsychoJS.Status.STARTED) {
      let theseKeys = sfm_kbd_continue.getKeys({keyList: ['space', 'up', 'down', 'left', 'right'], waitRelease: false});
      _sfm_kbd_continue_allKeys = _sfm_kbd_continue_allKeys.concat(theseKeys);
      if (_sfm_kbd_continue_allKeys.length > 0) {
        sfm_kbd_continue.keys = _sfm_kbd_continue_allKeys[_sfm_kbd_continue_allKeys.length - 1].name;  // just the last key pressed
        sfm_kbd_continue.rt = _sfm_kbd_continue_allKeys[_sfm_kbd_continue_allKeys.length - 1].rt;
        // a response ends the routine
        continueRoutine = false;
      }
    }
    
    
    // *sfm_text_message* updates
    if ((message_show) && sfm_text_message.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sfm_text_message.tStart = t;  // (not accounting for frame time here)
      sfm_text_message.frameNStart = frameN;  // exact frame index
      
      sfm_text_message.setAutoDraw(true);
    }

    
    // *sfm_text_steps_properties* updates
    if ((status_show) && sfm_text_steps_properties.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sfm_text_steps_properties.tStart = t;  // (not accounting for frame time here)
      sfm_text_steps_properties.frameNStart = frameN;  // exact frame index
      
      sfm_text_steps_properties.setAutoDraw(true);
    }

    
    // *sfm_text_steps_label* updates
    if ((status_show) && sfm_text_steps_label.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sfm_text_steps_label.tStart = t;  // (not accounting for frame time here)
      sfm_text_steps_label.frameNStart = frameN;  // exact frame index
      
      sfm_text_steps_label.setAutoDraw(true);
    }

    
    // *sfm_text_steps* updates
    if ((status_show) && sfm_text_steps.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sfm_text_steps.tStart = t;  // (not accounting for frame time here)
      sfm_text_steps.frameNStart = frameN;  // exact frame index
      
      sfm_text_steps.setAutoDraw(true);
    }

    
    // *sfm_text_coins_properties* updates
    if ((status_show) && sfm_text_coins_properties.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sfm_text_coins_properties.tStart = t;  // (not accounting for frame time here)
      sfm_text_coins_properties.frameNStart = frameN;  // exact frame index
      
      sfm_text_coins_properties.setAutoDraw(true);
    }

    
    // *sfm_text_coins_label* updates
    if ((status_show) && sfm_text_coins_label.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sfm_text_coins_label.tStart = t;  // (not accounting for frame time here)
      sfm_text_coins_label.frameNStart = frameN;  // exact frame index
      
      sfm_text_coins_label.setAutoDraw(true);
    }

    
    // *sfm_text_coins* updates
    if ((status_show) && sfm_text_coins.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sfm_text_coins.tStart = t;  // (not accounting for frame time here)
      sfm_text_coins.frameNStart = frameN;  // exact frame index
      
      sfm_text_coins.setAutoDraw(true);
    }

    
    // *sfm_polygon_status_bar_base* updates
    if ((status_show) && sfm_polygon_status_bar_base.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sfm_polygon_status_bar_base.tStart = t;  // (not accounting for frame time here)
      sfm_polygon_status_bar_base.frameNStart = frameN;  // exact frame index
      
      sfm_polygon_status_bar_base.setAutoDraw(true);
    }

    
    // *sfm_polygon_status_bar_apex* updates
    if ((status_show) && sfm_polygon_status_bar_apex.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sfm_polygon_status_bar_apex.tStart = t;  // (not accounting for frame time here)
      sfm_polygon_status_bar_apex.frameNStart = frameN;  // exact frame index
      
      sfm_polygon_status_bar_apex.setAutoDraw(true);
    }

    
    // *sfm_polygon_steps_bar* updates
    if ((status_show) && sfm_polygon_steps_bar.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sfm_polygon_steps_bar.tStart = t;  // (not accounting for frame time here)
      sfm_polygon_steps_bar.frameNStart = frameN;  // exact frame index
      
      sfm_polygon_steps_bar.setAutoDraw(true);
    }

    
    // *sfm_polygon_coin_bar* updates
    if ((status_show) && sfm_polygon_coin_bar.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sfm_polygon_coin_bar.tStart = t;  // (not accounting for frame time here)
      sfm_polygon_coin_bar.frameNStart = frameN;  // exact frame index
      
      sfm_polygon_coin_bar.setAutoDraw(true);
    }

    
    // *sfm_image_petey* updates
    if ((pigeon_show) && sfm_image_petey.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sfm_image_petey.tStart = t;  // (not accounting for frame time here)
      sfm_image_petey.frameNStart = frameN;  // exact frame index
      
      sfm_image_petey.setAutoDraw(true);
    }

    
    // *sfm_image_left_seeds* updates
    if ((seeds_show) && sfm_image_left_seeds.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sfm_image_left_seeds.tStart = t;  // (not accounting for frame time here)
      sfm_image_left_seeds.frameNStart = frameN;  // exact frame index
      
      sfm_image_left_seeds.setAutoDraw(true);
    }

    
    // *sfm_image_right_seeds* updates
    if ((seeds_show) && sfm_image_right_seeds.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sfm_image_right_seeds.tStart = t;  // (not accounting for frame time here)
      sfm_image_right_seeds.frameNStart = frameN;  // exact frame index
      
      sfm_image_right_seeds.setAutoDraw(true);
    }

    
    // *sfm_polygon_petey_midpoint* updates
    if ((status_show) && sfm_polygon_petey_midpoint.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sfm_polygon_petey_midpoint.tStart = t;  // (not accounting for frame time here)
      sfm_polygon_petey_midpoint.frameNStart = frameN;  // exact frame index
      
      sfm_polygon_petey_midpoint.setAutoDraw(true);
    }

    
    // *sfm_polygon_ordinate* updates
    if ((status_show) && sfm_polygon_ordinate.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sfm_polygon_ordinate.tStart = t;  // (not accounting for frame time here)
      sfm_polygon_ordinate.frameNStart = frameN;  // exact frame index
      
      sfm_polygon_ordinate.setAutoDraw(true);
    }

    
    // *sfm_polygon_abscissa* updates
    if ((pigeon_show) && sfm_polygon_abscissa.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sfm_polygon_abscissa.tStart = t;  // (not accounting for frame time here)
      sfm_polygon_abscissa.frameNStart = frameN;  // exact frame index
      
      sfm_polygon_abscissa.setAutoDraw(true);
    }

    
    // *sfm_polygon_box* updates
    if ((box_show) && sfm_polygon_box.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sfm_polygon_box.tStart = t;  // (not accounting for frame time here)
      sfm_polygon_box.frameNStart = frameN;  // exact frame index
      
      sfm_polygon_box.setAutoDraw(true);
    }

    
    // *sfm_text_instruction* updates
    if ((instruction_show) && sfm_text_instruction.status === PsychoJS.Status.NOT_STARTED) {
      // keep track of start time/frame for later
      sfm_text_instruction.tStart = t;  // (not accounting for frame time here)
      sfm_text_instruction.frameNStart = frameN;  // exact frame index
      
      sfm_text_instruction.setAutoDraw(true);
    }

    // check for quit (typically the Esc key)
    if (psychoJS.experiment.experimentEnded || psychoJS.eventManager.getKeys({keyList:['escape']}).length > 0) {
      return quitPsychoJS('The [Escape] key was pressed. Goodbye!', false);
    }
    
    // check if the Routine should terminate
    if (!continueRoutine) {  // a component has requested a forced-end of Routine
      return Scheduler.Event.NEXT;
    }
    
    continueRoutine = false;  // reverts to True if at least one component still running
    for (const thisComponent of show_final_messageComponents)
      if ('status' in thisComponent && thisComponent.status !== PsychoJS.Status.FINISHED) {
        continueRoutine = true;
        break;
      }
    
    // refresh the screen if continuing
    if (continueRoutine) {
      return Scheduler.Event.FLIP_REPEAT;
    } else {
      return Scheduler.Event.NEXT;
    }
  };
}


function show_final_messageRoutineEnd(snapshot) {
  return async function () {
    //--- Ending Routine 'show_final_message' ---
    for (const thisComponent of show_final_messageComponents) {
      if (typeof thisComponent.setAutoDraw === 'function') {
        thisComponent.setAutoDraw(false);
      }
    }
    sfm_kbd_continue.stop();
    // Run 'End Routine' code from sfm_code_update
    // Same bookkeeping as show_message's End Routine, kept for consistency; inert here since
    // this is the last routine in the experiment (quitPsychoJS runs next).
    trial_start = true;

    // the Routine "show_final_message" was not non-slip safe, so reset the non-slip timer
    routineTimer.reset();
    
    // Routines running outside a loop should always advance the datafile row
    if (currentLoop === psychoJS.experiment) {
      psychoJS.experiment.nextEntry(snapshot);
    }
    return Scheduler.Event.NEXT;
  }
}


function importConditions(currentLoop) {
  return async function () {
    psychoJS.importAttributes(currentLoop.getCurrentTrial());
    return Scheduler.Event.NEXT;
    };
}


async function quitPsychoJS(message, isCompleted) {
  // Check for and save orphaned data
  if (psychoJS.experiment.isEntryEmpty()) {
    psychoJS.experiment.nextEntry();
  }
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  psychoJS.window.close();
  psychoJS.quit({message: message, isCompleted: isCompleted});
  
  return Scheduler.Event.QUIT;
}
