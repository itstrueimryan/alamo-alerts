import re
import json
import boto3
import requests
from botocore.exceptions import ClientError


ALAMO_API_URL = 'https://drafthouse.com/s/mother/v2/schedule/market/nyc'
CURRENT_MOVIES_FILE = 'current-movies.json'
RECIPIENTS_FILE = 'recipients.txt'


def get_current_movies():
    f = open(CURRENT_MOVIES_FILE)
    current_movies = json.load(f)
    return current_movies


def get_new_movies():
    response = requests.get(ALAMO_API_URL)
    data = json.loads(response.content)
    presentations = data['data']['presentations']
    unique_slugs = set()
    movies = []

    for p in presentations:
        slug = p['show']['slug']
        if slug not in unique_slugs:
            unique_slugs.add(slug)
            img_url = re.sub(r'w=\d+', '',
                             p['show']['posterImages'][0]['uri'])
            img_url = re.sub(r'h=\d+', 'h=178', img_url)
            movies.append({
                'slug': slug,
                'title': p['show']['title'],
                'url': f'https://drafthouse.com/nyc/show/{slug}',
                'imgUrl': img_url
            })

    return sorted(movies, key=lambda k: k['slug'])


def get_movie_diff(current, incoming):
    results = {'existing': [], 'added': [], 'removed': []}
    p1 = 0
    p2 = 0

    while p1 < len(current) and p2 < len(incoming):
        first_slug = current[p1]['slug']
        second_slug = incoming[p2]['slug']

        if (first_slug == second_slug):
            results['existing'].append(current[p1])
            p1 += 1
            p2 += 1
        elif (first_slug < second_slug):
            results['removed'].append(current[p1])
            p1 += 1
        elif (first_slug > second_slug):
            results['added'].append(incoming[p2])
            p2 += 1

    for p in range(p1, len(current)):
        results['removed'].append(current[p])

    for p in range(p2, len(incoming)):
        results['added'].append(incoming[p])

    return results


def save_new_movies(movies):
    f = open(CURRENT_MOVIES_FILE, 'w')
    f.write(json.dumps(movies))
    f.close()


def send_alert(movie_diff):
    boto3.setup_default_session(profile_name='alamo-scraper-ses')

    # setup email properties
    sender = 'Alamo Alerts <info@alamo-alerts.com>'
    with open(RECIPIENTS_FILE) as f:
        recipients = list(f)
    subject = 'Movie updates at Alamo (NYC)'

    def movies_to_html(movies):
        if not len(movies):
            return '<p style="font-style: italic; margin-bottom: 45px">None detected.</p>'

        per_row = 4
        current = 0
        output = '<table><tr>'

        for movie in movies:
            if current == per_row:
                output += '</tr><tr>'
                current = 0

            output += f'<td><a href="{movie["url"]}"><img src="{movie["imgUrl"]}" /><p>{movie["title"]}</p></a></td>'
            current += 1

        return f'{output}</tr></table>'

    body = f"""<html>
                <head>
                <style>
                body {{
                    font-family: Arial;
                }}
                td p {{
                    font-size: 11px;
                    margin-top: 5px;
                    margin-bottom: 10px;
                    font-weight: bold;
                    color: #222;
                }}
                td {{
                    width: 120px;
                    overflow: hidden;
                    vertical-align: top;
                    padding: 0 5px;
                }}
                td a {{
                    display: block;
                    color: #000;
                    text-decoration: none;
                }}
                td a:hover p {{
                    text-decoration: underline;
                }}
                </style>
            </head>
                <body>
                <p>Changes to Alamo Drafthouse schedule detected:</p>

                <h2>New Movies</h2>
                {movies_to_html(movie_diff['added'])}

                <h2>Removed Movies</h2>
                {movies_to_html(movie_diff['removed'])}

                <h2>Existing Movies</h2>
                {movies_to_html(movie_diff['existing'])}
                </body>
            </html>
            """
    charset = 'utf-8'

    # send email
    client = boto3.client('ses', region_name='us-east-1')
    try:
        response = client.send_email(
            Destination={
                'ToAddresses': recipients,
            },
            Message={
                'Body': {
                    'Html': {
                        'Charset': charset,
                        'Data': body,
                    },
                },
                'Subject': {
                    'Charset': charset,
                    'Data': subject,
                },
            },
            Source=sender,
        )
    except ClientError as e:
        print(e.response['Error']['Message'])
    else:
        print("Email sent! Message ID:"),
        print(response['MessageId'])


if __name__ == '__main__':
    current_movies = get_current_movies()
    incoming_movies = get_new_movies()
    movie_diff = get_movie_diff(current_movies, incoming_movies)

    if len(movie_diff['added']) or len(movie_diff['removed']):
        save_new_movies(incoming_movies)
        send_alert(movie_diff)
