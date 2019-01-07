#compute the best opening book given
#given and a maximum number of moves to remember
#computes the most effective positions to memorize
#this works by taking in a list of real game positions
#(at least 20 instances of each position), together with
#the played responses to give a sense for how humans
#play out a position instead of relying entirely
#on stockfish evals


from eval_moves import Evaluator, hash_fen, fen_plus_move
import csv
from jtutils import pairwise



#read the graph of positions, along with the ev
EVALUATOR = Evaluator()

INPUT_FILE = "/tmp/filtered_moves.csv"
START_ZOBRIST = 5060803636482931868
EVAL_TIME = 1000

def add_marginal_evs(starting_ev, info):
    if not info: return
    info[0]["marginal_ev"] = info[0]["total_ev"] - starting_ev
    for x1,x2 in pairwise(info):
        x2["marginal_ev"] = x2["total_ev"] - x1["total_ev"]

def compute_p1_book(pos, prev_moves, n):
    #return the n moves to memorize that will give the greatest advantage
    #along with the value for memorizing the first k for k in [0,1,...n]

    #MUST: everywhere there's .children, consider if the node doesn't have children
    if pos.is_leaf():
        return {"starting_ev": pos.get_ev(), "info": []}

    books = {} #{node: {starting_ev: 0, info: [{moves: , total_ev: , marginal_ev:}]}}
    #step 1: compute book for each child node
    for child in pos.children:
        books[child] = compute_p2_book(child, prev_moves[:] + [pos.moves[child]], n)

    #now the real computation
    starting_ev = sum([books[child]["starting_ev"] * pos.probs[child] for child in pos.children])

    #step 2: we don't learn this position
    info_1 = aggregate_random_books(n, pos.children, pos.probs, books)["info"]


    #step 3: we do learn this position
    info_2 = []
    for k in range(n): #up to n-1 moves from the children
        options = [c for c in pos.children if len(books[c]["info"]) >= k]
        if len(options) == 0: continue
        def get_total_ev(x):
            if k == 0:
                return books[x]["starting_ev"]
            else:
                return books[x]["info"][k-1]["total_ev"]
        best_child = max(options, key=get_total_ev)
        best_total_ev = get_total_ev(best_child)

        total_ev = best_total_ev
        if k == 0:
            moves = [(prev_moves,pos.moves[best_child],total_ev)] #TODO: is total_ev necessarily the max ev? or does it include "oversized" books?
        else:
            moves = books[best_child]["info"][k-1]["moves"] + [(prev_moves,pos.moves[best_child],total_ev)]
        info_2.append({"moves":moves, "total_ev":total_ev})
    add_marginal_evs(starting_ev, info_2)

    #step 4: combine info_1 and info_2
    info = []
    for k in range(n):
        if len(info_1) > k and len(info_2) > k:
            if info_1[k]["total_ev"] > info_2[k]["total_ev"]:
                info.append(info_1[k])
            else:
                info.append(info_2[k])
        elif len(info_1) > k:
            info.append(info_1[k])
        elif len(info_2) > k:
            info.append(info_2[k])
        else:
            continue
    add_marginal_evs(starting_ev, info)

    return {"starting_ev": starting_ev, "info": info}

def compute_p2_book(pos, prev_moves, n):
    #compute the book for a node in which we aren't choosing a move
    #this could be because it's the opponent's turn
    if pos.is_leaf():
        return {"starting_ev": 1 - pos.get_ev(), "info": []}

    books = {}
    for child in pos.children:
        books[child] = compute_p1_book(child, prev_moves[:] + [pos.moves[child]], n)

    return aggregate_random_books(n, pos.children, pos.probs, books)

def aggregate_random_books(n, positions, probs, books):
    #if we have a random probability of reaching various positions
    #with prespecified opening books, which book should we choose for the root node?
    cnts = {p:0 for p in positions} #how many chosen from each child position
    #compute starting ev
    starting_ev = sum([books[p]["starting_ev"] * probs[p] for p in positions])
    info = []
    total_ev = starting_ev
    for _ in range(n):
        #all child moves used
        options = [p for p in positions if len(books[p]["info"]) > cnts[p]]
        if len(options) == 0: continue
        get_marginal_ev = lambda x: books[x]["info"][cnts[x]]["marginal_ev"] * probs[x]
        best_pos = max(options, key = get_marginal_ev)
        marginal_ev = get_marginal_ev(best_pos)
        moves = []
        cnts[best_pos] = cnts[best_pos] + 1
        for p in positions:
            if cnts[p] == 0: continue
            for m in books[p]["info"][cnts[p]-1]["moves"]:
                moves.append(m)
        total_ev += marginal_ev
        info.append({"moves":moves, "total_ev":total_ev})
    add_marginal_evs(starting_ev, info)
    return {"starting_ev": starting_ev, "info": info}


class GameNode:
    def __init__(self, val):
        super()
        self.val = val
        #must run set_info before using the node
        self.children = None
        self.moves = None #names of edges from this node to children
        self.probs = None #probabilities from this node to children
    def is_leaf(self):
        return len(self.children) == 0
    def set_info(self, children, moves, probs):
        self.children = children
        self.moves = moves
        self.probs = probs
    def get_ev(self):
        #average across the evaluations of the children, weighted by their probabilities
        #only allow this for leaf nodes
        if len(self.children) == 0:
            return EVALUATOR.evaluate(self.val, EVAL_TIME)[1]
        else:
            raise
    def __str__(self):
        return str(self.val) + '\n' + str(self.moves) + '\n' + str(self.probs)

def generate_position_graph():
    positions = {} #zobrist -> {fen, previous_moves, move_cnts:{move: cnt}}

    #position info
    with open(INPUT_FILE) as csvfile:
        reader = csv.DictReader(csvfile)
        for row in list(reader):
            zobrist = hash_fen(row["start_fen"])
            default = {"fen": row["start_fen"], "previous_moves": row["previous_moves"], "move_cnts":{}, "probs":{}}
            info = positions.setdefault(zobrist,default)
            info["move_cnts"][row["move"]] = info["move_cnts"].setdefault(row["move"],0) + 1

            #set child info if not set
            child_fen = fen_plus_move(row["start_fen"], row["move"])
            child_zobrist = hash_fen(child_fen)
            full_move_list = str(eval(row["previous_moves"]) + [row["move"]])
            default = {"fen": child_fen, "previous_moves": full_move_list, "move_cnts":{}, "probs":{}}
            positions.setdefault(child_zobrist,default)

            #set best move info if not set
            best_move = EVALUATOR.evaluate(row["start_fen"], EVAL_TIME)[0]
            best_move_fen = fen_plus_move(row["start_fen"], best_move)
            best_move_zobrist = hash_fen(best_move_fen)
            full_move_list = str(eval(row["previous_moves"]) + [best_move])
            default = {"fen": best_move_fen, "previous_moves": full_move_list, "move_cnts":{}, "probs":{}}
            positions.setdefault(best_move_zobrist, default)


    #warn if any positions have >0 and <20 moves --
    #this small n can ruin the data:
    #eg: make sure to play move X, which leads to a single game where the opponent
    #blunders their queen a few moves down the line
    for zobrist in positions:
        if sum(positions[zobrist]["move_cnts"].values()) > 0 and sum(positions[zobrist]["move_cnts"].values()) < 20:
            print('WARNING: positions with limited move counts')
            print(positions[zobrist]["previous_moves"])
            print(sum(positions[zobrist]["move_cnts"].values()))

    #compute move probabilities (these are the edge weights)
    for zobrist in positions:
        info = positions[zobrist]
        fen = info["fen"]

        #set counts
        total_cnt = 0
        for move in info["move_cnts"]:
            total_cnt += info["move_cnts"][move]

        for move in info["move_cnts"]:
            child_fen = fen_plus_move(fen, move)
            child_zobrist = hash_fen(child_fen)
            info["probs"][move] = info["move_cnts"][move] / total_cnt


        #add best_move as an edge with weight 0
        if total_cnt > 0: #skip this step for leaf nodes
            best_move = EVALUATOR.evaluate(fen, EVAL_TIME)[0]
            info["probs"].setdefault(best_move,0)

    #generate basic nodes for each position
    nodes = {} #zobrist -> node
    for zobrist in positions:
        nodes[zobrist] = GameNode(positions[zobrist]["fen"])

    #create graph by fully initializing node information
    for zobrist in nodes:
        info = positions[zobrist]
        fen = info["fen"]

        children = []
        moves = {}
        probs = {}

        #set children, probs, moves
        for move in positions[zobrist]["probs"]:
            child_fen = fen_plus_move(fen, move)
            child_zobrist = hash_fen(child_fen)
            child_node = nodes[child_zobrist]

            children.append(child_node)
            moves[child_node] = move
            probs[child_node] = positions[zobrist]["probs"][move]

        nodes[zobrist].set_info(children, moves, probs)
        nodes[zobrist].previous_moves = eval(positions[zobrist]["previous_moves"])

    for zobrist in nodes:
        pos = nodes[zobrist]
        sets = []
        sets.append(set(['e2e4', 'e7e5', 'f1c4', 'g8f6', 'd1f3']))
        sets.append(set(['e2e4', 'e7e5', 'f1c4', 'g8f6', 'd1f3', 'b8c6']))
        for s in sets:
            if set(pos.previous_moves) == s:
                print('evaluations')
                print(pos.previous_moves)
                ev = 0
                for c in pos.children:
                    ev += pos.probs[c] * EVALUATOR.evaluate(c.val, EVAL_TIME)[1]
                    print(pos.moves[c], pos.probs[c], EVALUATOR.evaluate(c.val, EVAL_TIME)[1])
                print(ev)

    return nodes[START_ZOBRIST]

def print_book(book):
    print(book["starting_ev"])
    #note: the best book might not be the one with the most moves!
    #TODO: throw out all too-large books
    #TODO: figure out how to augment the game tree such that more
    #      moves is always better
    best_book = max(book["info"], key = lambda x: x["total_ev"])
    print('move cnt:' + str(len(best_book["moves"])))
    for m in sorted(best_book["moves"], key=lambda x: x[0]):
        print(m)

if __name__ == "__main__":
    root_node = generate_position_graph()
    move_cnt = 200

    print("white")
    book = compute_p1_book(root_node, [], move_cnt)
    print_book(book)

    print("black")
    book = compute_p2_book(root_node, [], move_cnt)
    print_book(book)

    EVALUATOR.save_evals()