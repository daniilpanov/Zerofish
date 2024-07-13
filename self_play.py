import datetime
import os

import chess

import numpy as np
import tensorflow as tf

import game_state
import input_fn
import mcts
import model
import model_fn
import output_fn

starting_position = '4k3/8/8/8/8/8/8/3QK3 w - - 0 1'


def play_game(inference):
    # Initialize memory
    actions = []
    policies = []
    indices = []
    moves = []

    # Set up search tree
    state = game_state.GameState(fen=starting_position)
    tree = mcts.MCTS(inference, state, num_threads=8)

    # Play game
    while not tree.state.done():
        print(tree.state.state.unicode())

        # Perform search
        node = tree.search(128)

        N = node.N
        W = node.W
        P = node.P
        san = map(state.state.san, map(state.parse_action, node.actions))

        for n, w, p, s in zip(N, W, P, san):
            q = w / n
            print('{s}: n={n}, q={q}, p={p}'.format(n=n, q=q, p=p, s=s))

        # Calculate move probabilities and get action index
        probs = mcts.policy(node, T=1.0)
        index = np.random.choice(len(node.actions), p=probs)

        # Get action and update tree
        action = node.actions[index]
        value = node.W[index] / node.N[index]
        move = tree.state.parse_action(action)

        print(tree.state.state.san(move), value)

        tree.act(index)

        # Store stats
        actions.append(action)
        policies.append(probs)
        indices.append(node.actions)
        moves.append(move)

    # Get game outcome and last player to move
    outcome = -tree.state.reward()
    winner = not tree.state.turn()

    print(tree.state.state.unicode())
    print(' '.join([chess.Board(starting_position).variation_san(moves), state.state.result()]))

    return actions, policies, indices, outcome, winner


def write_game_records(out_file, actions, policies, indices, outcome, winner):
    # Create new state
    state = game_state.GameState(fen=starting_position)
    moves = []

    # Run through game to create feature vectors and produce output
    for i, action in enumerate(actions):
        # Extract features
        feature = state.observation().reshape((1, 8, 8, -1))

        # Calculate value of game based on who's to play
        value = outcome if state.turn() == winner else -outcome

        # Write example to disk
        example = output_fn.convert_example(feature, value, policies[i], indices[i])
        out_file.write(example.SerializeToString())

        # Update game state
        state.push_action(action)
        moves.append(state.state.peek())

    return moves


def write_records(data_dir, name, actions, policies, indices, outcome, winner):
    # Make directory for data if needed
    dirs = data_dir
    if not os.path.exists(dirs):
        print('making directories {}'.format(dirs))
        os.makedirs(dirs)

    path = os.path.join(dirs, name) + '.tfrecords'

    # Open tfrecords file
    options = tf.python_io.TFRecordOptions(tf.python_io.TFRecordCompressionType.GZIP)
    with tf.python_io.TFRecordWriter(path, options=options) as out_file:
        print('opened binary writer at {}'.format(path))
        moves = write_game_records(out_file, actions, policies, indices, outcome, winner)
    print('closed binary writer at {}'.format(path))

    return moves


def write_pgn(pgn_dir, name, moves, outcome, winner):
    dirs = pgn_dir
    if not os.path.exists(dirs):
        print('making directories {}'.format(dirs))
        os.makedirs(dirs)

    path = os.path.join(dirs, name) + '.pgn'
    pgn = [chess.Board(starting_position).variation_san(moves)]

    if outcome:
        if winner == chess.WHITE:
            pgn.append('1-0')
        else:
            pgn.append('0-1')
    else:
        pgn.append('1/2-1/2')

    with open(path, 'w') as out_file:
        print('opened {}'.format(path))
        print(' '.join(pgn), file=out_file)
    print('closed {}'.format(path))


def main(FLAGS, _):
    builder = model.ModelSpecBuilder(
        model_fn=model_fn.model_fn,
        model_dir=FLAGS.model_dir,
        config=model.cpu_config
    )

    inference_spec = builder.build_inference_spec(
        input_fn=input_fn.placeholder_input_fn(
            feature_names=('image',),
            feature_shapes=(FLAGS.input_shape,),
            feature_dtypes=(tf.int8,),
        ),

        params={
            'filters': FLAGS.filters,
            'modules': FLAGS.modules,
            'n_classes': FLAGS.n_classes
        }
    )

    inference = model.FeedingInferenceModel(inference_spec)

    with inference:
        actions, policies, indices, outcome, winner = play_game(inference)

    # Create file path
    name = datetime.datetime.utcnow().isoformat()

    moves = write_records(FLAGS.data_dir, name, actions, policies, indices, outcome, winner)
    write_pgn(FLAGS.pgn_dir, name, moves, outcome, winner)

    return 0


if __name__ == '__main__':
    import config
    import sys

    tf.logging.set_verbosity(tf.logging.INFO)

    FLAGS, unknown = config.get_FLAGS(config.config)
    exit(main(FLAGS, [sys.argv[0]] + unknown))
