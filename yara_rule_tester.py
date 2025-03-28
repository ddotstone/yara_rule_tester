import yara
import sqlite3
import sys
import yaml

verbose = False
list_flag = None
specific_proxy = None

def parse_config(config_file):
    with open(config_file, "r") as file:
        config = yaml.safe_load(file)
    proxy_entries = config['proxies']
    ips = []
    proxies = []
    rules = []
    for proxy in proxy_entries:
        ips.append(proxy['ip'])
        proxies.append(proxy['proxy'])
        rules.append(proxy['yara_ruleset'])
    return ips, proxies, rules

def load_yara_rules(yara_rules_paths):
    """Compiles YARA rules from a list of files."""
    rules = []
    for yara_rule_path in yara_rules_paths:
        print(f"Loading YARA rule from: {yara_rule_path}")  # Debug print
        try:
            rule = yara.compile(filepath=yara_rule_path)
            rules.append(rule)
        except yara.SyntaxError as e:
            print(f"YARA syntax error: {e}")
            sys.exit(1)
        except yara.Error as e:
            print(f"YARA error: {e}")
            sys.exit(1)
    return rules

def scan_text(rules, text):
    """Scans the given text using YARA rules."""
    matches = []
    for rule in rules:
        matches.extend(rule.match(data=text))
    return matches

def print_list(flag, id_text, headers_text, proxy_detected):
    if list_flag == flag:
        print(f"{flag} on id: {id_text}: Detected as {proxy_detected}\n{headers_text}\n")

def scan_sqlite_database(db_path, config_file):
    table_name = "ssl_logs"
    id_column_name = "id"
    ip_column_name = "ip"
    headers_column_name = "headers"
    ips, proxies, yara_rules_paths = parse_config(config_file)
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute(f"SELECT rowid, {id_column_name}, {headers_column_name}, {ip_column_name} FROM {table_name}")
        rows = cursor.fetchall()
        
        for i, ruleset_paths in enumerate(yara_rules_paths, start=0):
            if specific_proxy and proxies[i].lower() != specific_proxy.lower():
                continue

            print(f"\n========== Parsing Ruleset {proxies[i]} ==========\n")
            rules_true = load_yara_rules(ruleset_paths['should_be_true'])
            rules_false = load_yara_rules(ruleset_paths.get('should_be_false', []))  # Handle empty should_be_false
            total = 0
            total_from_proxy = 0
            total_not_from_proxy = 0
            fail = 0
            fail_from_proxy = 0
            fail_not_from_proxy = 0
            for rowid, id_text, headers_text, ip_text in rows:
                if headers_text:
                    matches_true = scan_text(rules_true, headers_text)
                    matches_false = scan_text(rules_false, headers_text)
                    if matches_true and not matches_false:
                        if ip_text != ips[i]:
                            fail += 1
                            fail_not_from_proxy += 1
                            total_not_from_proxy += 1
                            if verbose:
                                print(f"Failure on id: {id_text}: Detected as {proxies[i]} but request was not from proxy\n{headers_text}\n")
                            print_list("FP", id_text, headers_text, proxies[i])
                        else: 
                            total_from_proxy += 1
                            if verbose:
                                print(f"Success on id: {id_text}: Detected as {proxies[i]}\n{headers_text}\n")
                            print_list("TP", id_text, headers_text, proxies[i])
                    else:
                        if ip_text == ips[i]:
                            fail += 1
                            fail_from_proxy += 1
                            total_from_proxy += 1

                            if verbose:
                                print(f"Failure on id: {id_text}: Detected as {proxies[i]} but request was from proxy\n{headers_text}\n")
                            print_list("FN", id_text, headers_text, proxies[i])
                        else:
                            total_not_from_proxy += 1
                            print_list("TN", id_text, headers_text, proxies[i])
                total += 1
            
            TP = total_from_proxy - fail_from_proxy
            FP = fail_not_from_proxy
            TN = total_not_from_proxy - fail_not_from_proxy
            FN = fail_from_proxy
            
            # Calculate Precision, Recall, and F1 Score
            precision = TP / (TP + FP) if (TP + FP) > 0 else 0
            recall = TP / (TP + FN) if (TP + FN) > 0 else 0
            f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
            
            # Summary output
            print(f"Total Requests Parsed: {total}\n")
            print("Confusion Matrix:")
            print(f"True Positive (TP): {TP} | {100 * TP/total:.2f}%")
            print(f"False Positive (FP): {FP} | {100 * FP/total:.2f}%")
            print(f"True Negative (TN): {TN} | {100 * TN/total:.2f}%")
            print(f"False Negative (FN): {FN} | {100 * FN/total:.2f}%")
            print("\n")
            print(f"Precision: {precision:.2f}")
            print(f"Recall: {recall:.2f}")
            print(f"F1 Score: {f1_score:.2f}")
            print("\n")
            
        conn.close()
    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
        sys.exit(1)

if len(sys.argv) < 3:
    print("Usage: python yara_rule_tester.py <sqlite_db_file> <config_file> [-v] [flag=<tp|fp|tn|fn>] [proxy=<proxy_name>]")
    sys.exit(1)

sqlite_db_file = sys.argv[1]
config_file = sys.argv[2]
for arg in sys.argv[3:]:
    if arg == "-v":
        print("setting verbose")
        verbose = True
    elif arg.startswith("flag="):
        list_flag = arg.split("=")[1].upper()
    elif arg.startswith("proxy="):
        specific_proxy = arg.split("=")[1]

scan_sqlite_database(sqlite_db_file, config_file)